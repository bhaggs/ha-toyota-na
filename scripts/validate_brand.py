#!/usr/bin/env python3
"""Standalone validator for the ctpa-oneapi auth + vehicle-discovery flow.

Runs the same sequence the integration uses, with no Home Assistant import, so a
broken login or an empty vehicle list can be diagnosed in seconds instead of by
restarting HA and reading logs.

    pip install aiohttp pyjwt
    python scripts/validate_brand.py --brand S --username you@example.com

Toyota and Subaru share the ctpa-oneapi backend; only the ForgeRock tenant and a
few brand headers differ. The --no-appbrand / --no-brand-id / --no-bootstrap /
--user-agent flags exist to re-confirm *which* of those differences are actually
load-bearing, since that is undocumented and has changed before.

Prints counts, generations, and masked VINs only. Response bodies from this API
carry full VINs, precise location, and account details, so they are never
printed in full even at --verbose.
"""
import argparse
import asyncio
import getpass
import json
import logging
import sys
from urllib.parse import parse_qs, urlencode, urlparse

try:
    import aiohttp
except ImportError:
    sys.exit("Missing dependency: pip install aiohttp pyjwt")

_LOGGER = logging.getLogger("validate_brand")

API_GATEWAY = "https://onecdn.telematicsct.com/oneapi/"
RESOLVER_API_KEY = "pypIHG015k4ABHWbcI4G0a94F7cC0JDo1OynpAsG"

# Identical across brands - only the ForgeRock host and brand headers differ.
REALM_PATH = "realms/root/realms/tmna-native"
CLIENT_ID = "oneappsdkclient"
REDIRECT_URI = "com.toyota.oneapp:/oauth2Callback"
SCOPE = "openid profile write"

BRANDS = {
    "T": {
        "name": "Toyota",
        "auth_host": "login.toyotadriverslogin.com",
        "user_agent": (
            "ToyotaOneApp/3.10.0 (com.toyota.oneapp; build:3100; Android 14) okhttp/4.12.0"
        ),
        "bootstrap": False,
    },
    "S": {
        "name": "Subaru",
        "auth_host": "login.subarudriverslogin.com",
        "user_agent": (
            "SubaruConnect/3.10.0 (com.subaru.oneapp; build:3100; Android 14) okhttp/4.12.0"
        ),
        "bootstrap": True,
    },
}


def mask_vin(vin):
    """VINs identify a specific car and its owner - show only the last 4."""
    return f"...{vin[-4:]}" if vin else "???"


class Validator:
    def __init__(self, args):
        self.args = args
        self.brand = BRANDS[args.brand]
        host = self.brand["auth_host"]
        self.authenticate_url = f"https://{host}/json/{REALM_PATH}/authenticate"
        self.authorize_url = f"https://{host}/oauth2/{REALM_PATH}/authorize"
        self.access_token_url = f"https://{host}/oauth2/{REALM_PATH}/access_token"
        self.access_token = None
        self.guid = None

    def brand_headers(self, appbrand=None, brand_id=None):
        """The headers under test. Each can be suppressed to prove necessity."""
        appbrand = not self.args.no_appbrand if appbrand is None else appbrand
        brand_id = not self.args.no_brand_id if brand_id is None else brand_id
        headers = {"X-BRAND": self.args.brand}
        if appbrand:
            headers["X-APPBRAND"] = self.args.brand
        if brand_id:
            headers["X-Brand-Id"] = self.args.brand
        return headers

    def user_agent(self, which=None):
        which = which or self.args.user_agent
        if which == "toyota":
            return BRANDS["T"]["user_agent"]
        if which == "subaru":
            return BRANDS["S"]["user_agent"]
        return self.brand["user_agent"]

    async def authenticate(self, session, username, password):
        """ForgeRock callback loop. Returns the SSO tokenId."""
        headers = {"Accept-API-Version": "resource=2.1, protocol=1.0"}
        data = {}
        otp_prompted = False

        for _ in range(15):
            for cb in data.get("callbacks", []):
                cb_type = cb["type"]
                prompt = cb["output"][0].get("value", "") if cb.get("output") else ""

                if cb_type == "NameCallback":
                    if prompt == "User Name":
                        cb["input"][0]["value"] = username
                    elif prompt == "ui_locales":
                        cb["input"][0]["value"] = "en-US"
                elif cb_type == "PasswordCallback":
                    if prompt == "One Time Password":
                        # Prompt lazily: many accounts never reach this callback.
                        otp = input("One-time password (check email/SMS): ").strip()
                        cb["input"][0]["value"] = otp
                        otp_prompted = True
                    elif prompt == "Password":
                        cb["input"][0]["value"] = password
                elif cb_type == "ChoiceCallback":
                    cb["input"][0]["value"] = 0  # Local login
                elif cb_type == "ConfirmationCallback":
                    cb["input"][0]["value"] = 0  # Verify OTP
                elif cb_type == "TextOutputCallback":
                    if prompt == "Invalid OTP":
                        sys.exit("FAIL: invalid OTP")

            async with session.post(
                self.authenticate_url, json=data, headers=headers
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    _LOGGER.debug("authenticate body: %s", body[:500])
                    sys.exit(f"FAIL: authenticate returned HTTP {resp.status}")
                data = json.loads(body)
                if "tokenId" in data:
                    if otp_prompted:
                        print("  OTP accepted")
                    return data["tokenId"]

        sys.exit("FAIL: authenticate loop exhausted without a tokenId")

    async def authorize(self, session, token_id):
        """Exchange the SSO cookie for an OAuth authorization code."""
        params = {
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "code_challenge": "plain",
            "code_challenge_method": "plain",
        }
        headers = {"Cookie": f"iPlanetDirectoryPro={token_id}"}
        url = f"{self.authorize_url}?{urlencode(params)}"

        async with session.get(url, headers=headers, allow_redirects=False) as resp:
            if resp.status != 302:
                _LOGGER.debug("authorize body: %s", (await resp.text())[:500])
                sys.exit(f"FAIL: authorize returned HTTP {resp.status}, expected 302")
            query = parse_qs(urlparse(resp.headers["Location"]).query)
            if "code" not in query:
                sys.exit("FAIL: no authorization code in redirect")
            return query["code"][0]

    async def request_tokens(self, session, code):
        data = {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
            "code_verifier": "plain",
            "code": code,
        }
        async with session.post(self.access_token_url, data=data) as resp:
            body = await resp.text()
            if resp.status != 200:
                _LOGGER.debug("token body: %s", body[:500])
                sys.exit(f"FAIL: token exchange returned HTTP {resp.status}")
            tokens = json.loads(body)

        self.access_token = tokens["access_token"]
        # The GUID is the account identifier every gateway call is scoped to.
        import jwt

        claims = jwt.decode(
            tokens["id_token"],
            algorithms=["RS256"],
            options={"verify_signature": False},
            audience=CLIENT_ID,
        )
        self.guid = claims["sub"]
        return claims

    async def api_get(self, session, endpoint, brand_headers=None, user_agent=None):
        """GET against the shared ctpa-oneapi gateway. Returns (status, payload)."""
        headers = {
            "AUTHORIZATION": f"Bearer {self.access_token}",
            "X-API-KEY": RESOLVER_API_KEY,
            "X-GUID": self.guid,
            "X-CHANNEL": "ONEAPP",
            "x-region": "US",
            "X-APPVERSION": "3.4.0",
            "X-LOCALE": "en-US",
            "User-Agent": user_agent or self.user_agent(),
            "Accept": "application/json",
            **(brand_headers if brand_headers is not None else self.brand_headers()),
        }
        async with session.get(API_GATEWAY + endpoint, headers=headers) as resp:
            body = await resp.text()
            if resp.status >= 400:
                _LOGGER.debug("%s -> HTTP %d: %s", endpoint, resp.status, body[:500])
                return resp.status, None
            parsed = json.loads(body)
            return resp.status, parsed.get("payload", parsed)

    async def run_matrix(self, session):
        """Probe every open question on one login, since each login costs an OTP.

        Order matters. The bootstrap appears to initialize server-side session
        state, and that state may persist for the rest of the session -- so the
        no-bootstrap case has to run FIRST, before any v4/account call
        contaminates it. Everything after assumes bootstrap has happened.
        """
        print("  Running permutations on this one login.\n")
        results = []

        async def probe(label, *, bootstrap, appbrand=True, brand_id=True, ua=None):
            if bootstrap:
                await self.api_get(session, "v4/account")
            status, vehicles = await self.api_get(
                session,
                "v2/vehicle/guid",
                brand_headers=self.brand_headers(appbrand=appbrand, brand_id=brand_id),
                user_agent=self.user_agent(ua),
            )
            n = len(vehicles) if vehicles is not None else None
            verdict = "FAIL" if not n else f"{n} vehicle(s)"
            print(f"    {label:<34} HTTP {status}  {verdict}")
            results.append((label, n))
            return n

        # Must be first: no v4/account has been called yet in this session.
        no_bootstrap = await probe("no bootstrap, all headers", bootstrap=False)
        baseline = await probe("bootstrap + all headers", bootstrap=True)
        no_appbrand = await probe(
            "bootstrap, no X-APPBRAND", bootstrap=True, appbrand=False
        )
        no_brand_id = await probe(
            "bootstrap, no X-Brand-Id", bootstrap=True, brand_id=False
        )
        wrong_ua = await probe("bootstrap, Toyota User-Agent", bootstrap=True, ua="toyota")

        print("\n  --- conclusions ---")
        if not baseline:
            print("    Baseline failed; everything below is meaningless.")
            return 1
        print(
            "    v4/account bootstrap : "
            + ("REQUIRED" if not no_bootstrap else "not required (worked without it)")
        )
        print(
            "    X-APPBRAND           : "
            + ("REQUIRED" if not no_appbrand else "not load-bearing")
        )
        print(
            "    X-Brand-Id           : "
            + ("REQUIRED" if not no_brand_id else "not load-bearing")
        )
        print(
            "    Brand User-Agent     : "
            + ("REQUIRED" if not wrong_ua else "not checked by the backend")
        )
        print(
            "\n  Anything marked 'not load-bearing' can be dropped from\n"
            "  oneapi/brands.py; anything REQUIRED is confirmed and should stay.\n"
        )
        return 0

    async def run_two_phase(self, username, password):
        """Reproduce the config flow's split-session OTP flow.

        Home Assistant asks for the OTP in a separate step, so authorize() runs
        twice, each in its own ClientSession. ForgeRock pins a session to one
        cluster node with the amlbcookie affinity cookie, so unless a cookie jar
        outlives both calls, phase two lands on a node that never issued our
        authId and the OTP is rejected as invalid.

        --no-shared-cookies drops the jar to demonstrate the failure.
        """
        shared = None if self.args.no_shared_cookies else aiohttp.CookieJar()
        print(
            "  cookie jar across phases: "
            + ("NONE (reproducing the bug)" if shared is None else "shared (the fix)")
        )

        def new_session():
            return aiohttp.ClientSession(
                cookie_jar=shared if shared is not None else aiohttp.CookieJar()
            )

        headers = {"Accept-API-Version": "resource=2.1, protocol=1.0"}
        data, stash = {}, None

        # Phase 1: run until the backend asks for an OTP, then stop and close.
        async with new_session() as session:
            for _ in range(15):
                asked = False
                for cb in data.get("callbacks", []):
                    prompt = cb["output"][0].get("value", "") if cb.get("output") else ""
                    if cb["type"] == "NameCallback":
                        if prompt == "User Name":
                            cb["input"][0]["value"] = username
                        elif prompt == "ui_locales":
                            cb["input"][0]["value"] = "en-US"
                    elif cb["type"] == "PasswordCallback":
                        if prompt == "One Time Password":
                            asked = True
                            break
                        if prompt == "Password":
                            cb["input"][0]["value"] = password
                    elif cb["type"] in ("ChoiceCallback", "ConfirmationCallback"):
                        cb["input"][0]["value"] = 0
                if asked:
                    stash = data
                    break
                async with session.post(
                    self.authenticate_url, json=data, headers=headers
                ) as r:
                    if r.status != 200:
                        sys.exit(f"FAIL phase 1: HTTP {r.status}")
                    data = json.loads(await r.text())
                    if "tokenId" in data:
                        print("  [!!] no OTP was requested; nothing to reproduce")
                        return 0
        print("  [ok] phase 1 complete, session closed")
        if stash is None:
            sys.exit("FAIL: never reached an OTP prompt")

        otp = input("  One-time password: ").strip()
        for cb in stash.get("callbacks", []):
            prompt = cb["output"][0].get("value", "") if cb.get("output") else ""
            if cb["type"] == "PasswordCallback" and prompt == "One Time Password":
                cb["input"][0]["value"] = otp
            elif cb["type"] == "ConfirmationCallback":
                cb["input"][0]["value"] = 0

        # Phase 2: brand-new session, exactly as the config flow does it.
        async with new_session() as session:
            async with session.post(
                self.authenticate_url, json=stash, headers=headers
            ) as r:
                body = await r.text()
                if r.status != 200:
                    print(f"\n  [FAIL] phase 2 rejected: HTTP {r.status}")
                    print(f"         {body[:200]}")
                    print(
                        "\n  This is the HA failure. The OTP was correct; the request\n"
                        "  reached a node that never issued the authId."
                    )
                    return 1
                out = json.loads(body)
                if "tokenId" in out:
                    print("\n  [ok] phase 2 accepted across separate sessions")
                    return 0
                print(f"\n  [FAIL] no tokenId; callbacks={[c['type'] for c in out.get('callbacks',[])]}")
                return 1

    async def run(self):
        username = self.args.username or input("Username: ")
        password = self.args.password or getpass.getpass("Password: ")

        print(f"\n=== {self.brand['name']} (X-BRAND: {self.args.brand}) ===")
        print(f"  auth host       : {self.brand['auth_host']}")
        print(f"  brand headers   : {', '.join(sorted(self.brand_headers()))}")
        print(f"  user-agent      : {self.user_agent().split(' ')[0]}")
        bootstrap = self.brand["bootstrap"] and not self.args.no_bootstrap
        print(f"  /v4/account     : {'yes' if bootstrap else 'no'}\n")

        if self.args.two_phase:
            return await self.run_two_phase(username, password)

        async with aiohttp.ClientSession() as session:
            token_id = await self.authenticate(session, username, password)
            print("  [ok] authenticate")

            code = await self.authorize(session, token_id)
            print("  [ok] authorize")

            claims = await self.request_tokens(session, code)
            print(f"  [ok] tokens (guid {claims['sub'][:8]}...)")

            # The config flow identifies the account from these claims. Print the
            # key names (never the values - they are personal data) so a missing
            # one is obvious rather than surfacing as a generic UI error.
            print(f"  [--] id_token claims: {', '.join(sorted(claims))}")
            print(
                "  [--] email claim: "
                + ("present" if claims.get("email") else "ABSENT - falls back to sub")
            )

            if self.args.matrix:
                print()
                return await self.run_matrix(session)

            if bootstrap:
                status, payload = await self.api_get(session, "v4/account")
                if payload is None:
                    print(f"  [!!] v4/account HTTP {status} - continuing anyway")
                else:
                    print("  [ok] v4/account bootstrap")

            status, vehicles = await self.api_get(session, "v2/vehicle/guid")
            if vehicles is None:
                sys.exit(f"\nFAIL: v2/vehicle/guid returned HTTP {status}")

            print(f"\n  {len(vehicles)} vehicle(s) returned\n")
            if not vehicles:
                print(
                    "  Empty list with a 200 is the known symptom of a missing\n"
                    "  brand header or a skipped /v4/account bootstrap."
                )
                return 1

            for v in vehicles:
                print(
                    f"    {v.get('modelYear', '?')} {v.get('modelName', '?')}"
                    f"  vin={mask_vin(v.get('vin'))}"
                    f"  gen={v.get('generation', '?')}"
                    f"  ev={v.get('evVehicle')}"
                    f"  sub={v.get('remoteSubscriptionStatus', '?')}"
                )
            print()
            return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate ctpa-oneapi auth and vehicle discovery for one brand.",
    )
    parser.add_argument("--brand", choices=["T", "S"], default="T")
    parser.add_argument("--username")
    parser.add_argument("--password", help="omit to be prompted securely")
    parser.add_argument(
        "--two-phase",
        action="store_true",
        help="reproduce Home Assistant's split-session OTP flow, where authorize "
        "runs once to request the code and again to submit it",
    )
    parser.add_argument(
        "--no-shared-cookies",
        action="store_true",
        help="with --two-phase, drop the cookie jar between phases to demonstrate "
        "the ForgeRock affinity failure",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="probe every header/bootstrap permutation on a single login, so "
        "answering all the open questions costs one OTP instead of five",
    )
    parser.add_argument(
        "--no-appbrand",
        action="store_true",
        help="suppress X-APPBRAND to test whether it is load-bearing",
    )
    parser.add_argument(
        "--no-brand-id",
        action="store_true",
        help="suppress X-Brand-Id to test whether it is load-bearing",
    )
    parser.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="skip the /v4/account call that Subaru appears to require",
    )
    parser.add_argument(
        "--user-agent",
        choices=["match", "toyota", "subaru"],
        default="match",
        help="send a deliberately mismatched UA to test whether it is checked",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="  %(message)s",
    )
    sys.exit(asyncio.run(Validator(args).run()) or 0)


if __name__ == "__main__":
    main()
