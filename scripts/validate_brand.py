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

--probe asks, read-only, which endpoints the North American gateway serves for
each vehicle, and prints the shape of what comes back (key names and types,
never values). The candidates come from the European integration
(pytoyoda/ha_toyota), which runs on the same platform with more features. It
also prints the charging-schedule and climate fields of the EV status in full,
since those hold settings rather than identity and can't be decoded from shape.

--climate-write-test is the one flag here that writes. It checks whether the
saved remote-climate settings can be changed, by the PUT the European
integration used before July 2026: it raises the target temperature by 1
degree, reads it back, and restores the original. Settings only apply the next
time remote climate starts, so nothing reaches the vehicle. It asks first.
"""
import argparse
import asyncio
import getpass
import json
import logging
import sys
from datetime import date, timedelta
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


def _trips_endpoint():
    """The last week's trip summaries, without routes, as the EU app asks."""
    today = date.today()
    return "v1/trips?" + urlencode({
        "from": (today - timedelta(days=7)).isoformat(),
        "to": today.isoformat(),
        "route": "false",
        "summary": "true",
        "limit": 5,
        "offset": 0,
    })


# (label, endpoint) - GETs only. Every one reads; none reaches the vehicle.
PROBE_ENDPOINTS = [
    # Climate state and settings: target temperature, defrost, seat and
    # steering heaters, and (EU) the cabin temperature. The v1/vehicle/* paths
    # are where Toyota EU moved in July 2026; the v1/global/remote/* ones are
    # where they were before.
    ("climate status", "v1/vehicle/climate-status"),
    ("climate settings", "v1/vehicle/climate-settings"),
    ("climate status (older path)", "v1/global/remote/climate-status"),
    ("climate settings (older path)", "v1/global/remote/climate-settings"),
    # Warning lights, oil, and possibly the key fob battery. The integration's
    # client has methods for both and nothing calls them.
    ("vehicle health status", "v1/vehiclehealth/status"),
    ("vehicle health report", "v1/vehiclehealth/report"),
    ("notification history", "v2/notification/history"),
    ("trips, last 7 days", _trips_endpoint()),
    ("service history", "v1/servicehistory/vehicle/summary"),
    # What the Remote start switch reads its on/off state from.
    ("remote start status", "v1/global/remote/engine-status"),
    # Where Toyota EU reads door/lock status since July 2026. Serving it here
    # would be early warning that NA may follow.
    ("vehicle status (EU path)", "v1/vehicle/status"),
]

# Values printed alongside the shape, for endpoints whose fields can't be
# decoded from key names alone. ALL prints the whole payload; otherwise a tuple
# of key prefixes. Only settings and status go here - never the VIN, location,
# odometer or anything else that identifies the car or its owner.
ALL = "all"
PROBE_VALUES = {
    # Climate settings: the target temperature and what each of the four
    # acOperations categories is. Temperatures and switches only.
    "v1/vehicle/climate-settings": ALL,
    "v1/global/remote/climate-settings": ALL,
    # Remote start status: on/off, start time and minutes remaining. The
    # payload also carries the VIN, so name the fields rather than print ALL.
    "v1/global/remote/engine-status": ("status", "date", "timer"),
    # Key fob battery and warning lights. Leaves out vin, mileage and fuel.
    "v1/vehiclehealth/status": ("smartKeyBat", "warning", "wnglastUpdTime"),
    # Recalls, service campaigns and alerts, and when the report was generated
    # (auditTrail.vhrgenTime), to see whether it is current. Leaves out
    # vehicleDetails and maintenanceInformation, which carry the VIN and mileage.
    "v1/vehiclehealth/report": (
        "status", "auditTrail", "recallsListExists", "campaignsExists",
        "vehicleAlertsExists", "safetyRecallsList", "serviceCampaignList",
        "serviceCampaigns",
        "vehicleAlertList",
        # The key fob as the app's Health tab shows it, nested in vehicleStatus.
        "vehicleStatus.smartKeyBatteryTitle",
        "vehicleStatus.smartKeyBatteryDesc",
        "vehicleStatus.smartKeyBatteryDegStatus",
    ),
}

# Printed in full, not as a shape: settings, not identity, and meaningless
# without the values. Paths are into the v2/electric/status payload.
PROBE_VALUE_FIELDS = [
    # When the vehicle took this reading. Without it, an unchanged value can't
    # be told apart from a stale one.
    ("reading taken at", ("vehicleInfo", "acquisitionDatetime")),
    ("charging schedule", ("vehicleInfo", "timerChargeInfo")),
    ("charging schedule slots", ("vehicleInfo", "maxNoOfChargeSchedules")),
    ("remote climate", ("vehicleInfo", "remoteHvacInfo")),
]


def shape(value, depth=0, max_depth=4):
    """Describe a payload by key names and types, never values.

    Lists show their length and the shape of the first item, which is enough to
    see what an endpoint offers without printing anything personal.
    """
    pad = "  " * depth
    if isinstance(value, dict):
        if not value:
            return "{}"
        if depth >= max_depth:
            return "{...}"
        lines = [
            f"{pad}  {key}: {shape(item, depth + 1, max_depth).lstrip()}"
            for key, item in value.items()
        ]
        return "\n" + "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[] (empty)"
        return f"list of {len(value)}, first:" + shape(value[0], depth, max_depth)
    return "null" if value is None else type(value).__name__


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

    async def probe_get(self, session, endpoint, vin):
        """GET one vehicle-scoped endpoint. Returns (status, payload, error_code)."""
        return await self.probe_request(session, "GET", endpoint, vin)

    async def probe_request(self, session, method, endpoint, vin, body=None):
        """Call one vehicle-scoped endpoint. Returns (status, payload, error_code).

        The error code is the gateway's own (e.g. ONE-GLOBAL-RS-40009 or
        APIGW-403): generic, and the quickest way to tell "not served here"
        from "served, but not for this vehicle".
        """
        headers = {
            "AUTHORIZATION": f"Bearer {self.access_token}",
            "X-API-KEY": RESOLVER_API_KEY,
            "X-GUID": self.guid,
            "X-CHANNEL": "ONEAPP",
            "x-region": "US",
            "X-APPVERSION": "3.4.0",
            "X-LOCALE": "en-US",
            "User-Agent": self.user_agent(),
            "Accept": "application/json",
            "VIN": vin,
            **self.brand_headers(),
        }
        async with session.request(
            method, API_GATEWAY + endpoint, headers=headers, json=body
        ) as resp:
            body = await resp.text()
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            if resp.status >= 400:
                code = None
                if isinstance(parsed, dict):
                    status = parsed.get("status")
                    if isinstance(status, dict) and status.get("messages"):
                        code = status["messages"][0].get("responseCode")
                    code = code or parsed.get("code") or parsed.get("message")
                return resp.status, None, code
            if isinstance(parsed, dict):
                parsed = parsed.get("payload", parsed)
            return resp.status, parsed, None

    async def run_probe(self, session, vehicles):
        """Ask which EU-integration endpoints this gateway serves, per vehicle."""
        for v in vehicles:
            vin = v.get("vin")
            print(f"  --- {v.get('modelYear', '?')} {v.get('modelName', '?')}"
                  f"  vin={mask_vin(vin)}  gen={v.get('generation', '?')} ---\n")

            for label, endpoint in PROBE_ENDPOINTS:
                path = endpoint.split("?")[0]
                status, payload, code = await self.probe_get(session, endpoint, vin)
                if payload is None:
                    detail = f"  {code}" if code else ""
                    print(f"    [{status}] {label:<30} {path}{detail}")
                else:
                    print(f"    [{status}] {label:<30} {path}  SERVED:"
                          f"{shape(payload, 2)}")
                    wanted = PROBE_VALUES.get(path)
                    if wanted == ALL:
                        values = payload
                    elif wanted and isinstance(payload, dict):
                        top = tuple(w for w in wanted if "." not in w)
                        values = {
                            key: item for key, item in payload.items()
                            if top and key.startswith(top)
                        }
                        # "a.b" names one nested field exactly.
                        for dotted in (w for w in wanted if "." in w):
                            item = payload
                            for part in dotted.split("."):
                                item = item.get(part) if isinstance(item, dict) else None
                            values[dotted] = item
                    else:
                        values = None
                    if values is not None:
                        text = json.dumps(values, indent=2).replace("\n", "\n        ")
                        print(f"      values: {text}")
                # Stay well clear of the gateway's rate limiting.
                await asyncio.sleep(1)

            print("\n    EV status fields, in full:")
            status, electric, code = await self.probe_get(
                session, "v2/electric/status", vin
            )
            if electric is None:
                print(f"    [{status}] v2/electric/status failed  {code or ''}")
            else:
                for label, path in PROBE_VALUE_FIELDS:
                    value = electric
                    for key in path:
                        value = value.get(key) if isinstance(value, dict) else None
                    text = json.dumps(value, indent=2).replace("\n", "\n        ")
                    print(f"      {label}: {text}")
            print()
        print(
            "  A 200 with a shape is served. 404 or 403 usually means not served\n"
            "  here; other codes may be served but refused for this vehicle.\n"
            "  To decode the charging schedule, set one in the app, press Poll\n"
            "  vehicle in Home Assistant, then run this again and compare.\n"
        )
        return 0

    async def run_climate_write_test(self, session, vehicles):
        """Change the saved climate temperature by 1 degree, read it back, restore.

        The body is the settings as read, minus the three range fields the read
        adds, which is the shape the European integration's PUT sent. Restoring
        writes the original back whether or not the change appeared to take,
        since a write can land even when its response looks like a refusal.
        """
        endpoint = "v1/global/remote/climate-settings"
        read_only = ("minTemp", "maxTemp", "tempInterval")
        failed = False

        for v in vehicles:
            vin = v.get("vin")
            print(f"  --- climate write test: {v.get('modelYear', '?')} "
                  f"{v.get('modelName', '?')}  vin={mask_vin(vin)} ---\n")

            status, original, code = await self.probe_get(session, endpoint, vin)
            if not isinstance(original, dict) or original.get("temperature") is None:
                print(f"    [{status}] can't read the settings  {code or ''}\n")
                failed = True
                continue

            unit = original.get("temperatureUnit", "")
            before = original["temperature"]
            step = original.get("tempInterval") or 1
            changed = before + step
            if original.get("maxTemp") is not None and changed > original["maxTemp"]:
                changed = before - step
            print(f"    saved target temperature: {before} {unit}")
            print(f"    will set it to {changed} {unit}, read it back, then restore "
                  f"{before} {unit}.")
            print("    Nothing is sent to the vehicle.")
            if input("    Type yes to continue: ").strip().lower() != "yes":
                print("    skipped\n")
                continue

            restore = {k: val for k, val in original.items() if k not in read_only}
            trial = {**restore, "temperature": changed}

            status, payload, code = await self.probe_request(
                session, "PUT", endpoint, vin, trial
            )
            print(f"\n    [{status}] PUT {endpoint}  {code or ''}")
            if isinstance(payload, dict) and payload:
                print(f"      response keys: {', '.join(sorted(payload))}")
                if "returnCode" in payload:
                    print(f"      returnCode: {payload['returnCode']}")

            await asyncio.sleep(2)
            _, after, _ = await self.probe_get(session, endpoint, vin)
            read_back = after.get("temperature") if isinstance(after, dict) else None
            print(f"    read back: {read_back} {unit}")
            if read_back == changed:
                print("    WRITABLE: the change was saved.")
            elif read_back == before:
                print("    NOT WRITABLE: the setting did not change.")
            else:
                print("    UNCLEAR: read back neither value.")

            await asyncio.sleep(1)
            status, _, code = await self.probe_request(
                session, "PUT", endpoint, vin, restore
            )
            await asyncio.sleep(2)
            _, final, _ = await self.probe_get(session, endpoint, vin)
            restored = final.get("temperature") if isinstance(final, dict) else None
            if restored == before:
                print(f"    [ok] restored to {before} {unit}\n")
            else:
                failed = True
                print(
                    f"    [!!] RESTORE FAILED (HTTP {status} {code or ''}): the saved "
                    f"temperature reads {restored} {unit}.\n"
                    f"         Set it back to {before} {unit} in the SubaruConnect app.\n"
                )
        return 1 if failed else 0

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
            result = 0
            if self.args.probe:
                result = await self.run_probe(session, vehicles)
            if self.args.climate_write_test:
                result = await self.run_climate_write_test(session, vehicles) or result
            return result


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
        "--probe",
        action="store_true",
        help="after discovery, check read-only which extra endpoints (climate, "
        "vehicle health, trips, ...) this gateway serves, and print the EV "
        "status's charging-schedule and climate fields",
    )
    parser.add_argument(
        "--climate-write-test",
        action="store_true",
        help="WRITES: change the saved climate temperature by 1 degree, read it "
        "back, and restore it, to test whether climate settings are writable. "
        "Asks before writing; nothing is sent to the vehicle",
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
