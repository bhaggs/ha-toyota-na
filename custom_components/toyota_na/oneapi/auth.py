"""ForgeRock authentication against a brand's driver-login tenant.

Vendored from toyota-na's ToyotaOneAuth rather than subclassed: upstream reads
its endpoint URLs as `ToyotaOneAuth.ACCESS_TOKEN_URL` -- explicit class access,
not `self.` -- so a subclass cannot redirect them, and the only alternative was
mutating class attributes at import time. That is global state: a Toyota and a
Subaru config entry in one HA instance would overwrite each other's endpoints.
Here the URLs are per-instance, derived from the brand passed to __init__.

The callback loop also carries this fork's OTP support, which upstream lacks.
"""
import json
import logging
import random
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
import jwt

from toyota_na.exceptions import LoginError, NotLoggedIn, TokenExpired

from .brands import CLIENT_ID, DEFAULT_BRAND, REDIRECT_URI, SCOPE, get_brand

_LOGGER = logging.getLogger(__name__)


class OneAuth:
    """Token lifecycle for one account on one brand."""

    def __init__(
        self, brand=DEFAULT_BRAND, callback=None, initial_tokens=None, refresh_secs=300
    ):
        self.brand = get_brand(brand)
        self._callback = callback
        self._refresh_secs = refresh_secs
        self._access_token = None
        self._refresh_token = None
        self._id_token = None
        self._guid = None
        self._expires_at = None
        self._updated_at = None
        self._device_id = None
        self.otp_callbacks = None
        # Built lazily in _session(): aiohttp.CookieJar() requires a running
        # event loop, and this class must stay constructible from sync code.
        self._cookie_jar = None
        if initial_tokens:
            try:
                self.set_tokens(initial_tokens)
            except (KeyError, TypeError):
                # Malformed stored tokens just mean we re-authenticate.
                _LOGGER.debug("Ignoring unusable stored tokens")

    def _session(self):
        """Session sharing one cookie jar across every call in the auth flow.

        ForgeRock is clustered and pins a session to a single node with the
        amlbcookie affinity cookie. The OTP flow spans two authorize() calls --
        one to request the code, one to submit it -- and each opens its own
        ClientSession. Without a jar outliving them, the second call carries no
        affinity cookie, reaches a node that never issued our authId, and the
        backend rejects a perfectly valid OTP as invalid.
        """
        if self._cookie_jar is None:
            self._cookie_jar = aiohttp.CookieJar()
        return aiohttp.ClientSession(cookie_jar=self._cookie_jar)

    async def authorize(self, username, password, otp=None):
        """Run the ForgeRock callback loop and return an authorization code.

        Handles both the password flow and the newer passwordless OTP flow. When
        the server asks for an OTP and none was supplied, the in-progress
        callbacks are stashed and returned; the caller re-invokes with `otp` set
        to resume the same session.
        """
        async with self._session() as session:
            headers = {"Accept-API-Version": "resource=2.1, protocol=1.0"}

            data = self.otp_callbacks if otp is not None else {}
            awaiting_otp = False

            for _ in range(15):
                for cb in data.get("callbacks", []):
                    cb_type = cb["type"]
                    prompt = cb["output"][0].get("value", "") if cb.get("output") else ""
                    _LOGGER.debug("Callback: %s - %s", cb_type, prompt)

                    if cb_type == "NameCallback":
                        if prompt == "User Name":
                            cb["input"][0]["value"] = username
                        elif prompt == "ui_locales":
                            cb["input"][0]["value"] = "en-US"

                    elif cb_type == "PasswordCallback":
                        if prompt == "One Time Password":
                            if otp is None:
                                awaiting_otp = True
                                break
                            cb["input"][0]["value"] = otp
                        elif prompt == "Password":
                            cb["input"][0]["value"] = password

                    elif cb_type == "ChoiceCallback":
                        # Login method: Local=0, Google=1, Facebook=2, Apple=3
                        cb["input"][0]["value"] = 0

                    elif cb_type == "ConfirmationCallback":
                        # Verify OTP=0, Resend OTP=1
                        cb["input"][0]["value"] = 0

                    elif cb_type == "HiddenValueCallback":
                        pass  # devicePrint etc - pass through unchanged

                    elif cb_type == "TextOutputCallback":
                        if prompt == "Invalid OTP":
                            _LOGGER.error("Invalid OTP")
                            raise LoginError()

                if awaiting_otp:
                    # Stash so the follow-up call resumes this same auth session.
                    self.otp_callbacks = data
                    _LOGGER.debug("Awaiting OTP from user")
                    return data

                async with session.post(
                    self.brand.authenticate_url, json=data, headers=headers
                ) as resp:
                    body = await resp.text()
                    if resp.status != 200:
                        _LOGGER.debug(
                            "authenticate -> HTTP %d: %s", resp.status, body[:500]
                        )
                        raise LoginError()
                    data = json.loads(body)
                    if "tokenId" in data:
                        break

            if "tokenId" not in data:
                _LOGGER.error("Authentication did not yield a token")
                raise LoginError()

            headers["Cookie"] = f"iPlanetDirectoryPro={data['tokenId']}"
            auth_params = {
                "client_id": CLIENT_ID,
                "scope": SCOPE,
                "response_type": "code",
                "redirect_uri": REDIRECT_URI,
                "code_challenge": "plain",
                "code_challenge_method": "plain",
            }
            authorize_url = f"{self.brand.authorize_url}?{urlencode(auth_params)}"
            async with session.get(
                authorize_url, headers=headers, allow_redirects=False
            ) as resp:
                if resp.status != 302:
                    _LOGGER.debug(
                        "authorize -> HTTP %d: %s", resp.status, (await resp.text())[:500]
                    )
                    raise LoginError()
                redir = resp.headers["Location"]
                query = parse_qs(urlparse(redir).query)
                if "code" not in query:
                    _LOGGER.error("No authorization code in redirect")
                    raise LoginError()
                return query["code"][0]

    async def login(self, username, password, otp=None):
        authorization_code = await self.authorize(username, password, otp)
        await self.request_tokens(authorization_code)

    async def request_tokens(self, code):
        await self._token_request(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": "plain",
                "code": code,
            }
        )

    async def refresh_tokens(self):
        await self._token_request(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "refresh_token",
                "code_verifier": "plain",
                "refresh_token": self._refresh_token,
            }
        )

    async def _token_request(self, data):
        # Same jar: the token exchange belongs to the same pinned auth session.
        async with self._session() as session:
            async with session.post(self.brand.access_token_url, data=data) as resp:
                body = await resp.text()
                if resp.status != 200:
                    _LOGGER.debug("token -> HTTP %d: %s", resp.status, body[:500])
                    raise LoginError()
                self._extract_tokens(json.loads(body))

    async def check_tokens(self):
        if self._expires_at is None:
            raise NotLoggedIn()
        now = datetime.utcnow().timestamp()
        if self._expires_at < now:
            try:
                await self.refresh_tokens()
            except LoginError:
                raise TokenExpired()
        elif self._refresh_secs > 0 and now > self._updated_at + self._refresh_secs:
            await self.refresh_tokens()
        elif self._refresh_secs < 0 and now > self._expires_at + self._refresh_secs:
            await self.refresh_tokens()
        elif self._refresh_secs == 0:
            await self.refresh_tokens()

    def logged_in(self):
        return bool(
            self._expires_at and self._expires_at > datetime.utcnow().timestamp()
        )

    def _extract_tokens(self, token_resp):
        self._id_token = token_resp["id_token"]
        self._access_token = token_resp["access_token"]
        self._refresh_token = token_resp["refresh_token"]
        self._guid = self._decode_id_token()["sub"]
        self._expires_at = datetime.utcnow().timestamp() + token_resp["expires_in"]
        self._updated_at = datetime.utcnow().timestamp()
        if self._callback:
            try:
                self._callback(self.get_tokens())
            except Exception:
                _LOGGER.exception("Token callback failed")

    def _decode_id_token(self):
        return jwt.decode(
            self._id_token,
            algorithms=["RS256"],
            options={"verify_signature": False},
            audience=CLIENT_ID,
        )

    async def get_access_token(self):
        await self.check_tokens()
        return self._access_token

    async def get_guid(self):
        await self.check_tokens()
        return self._guid

    async def get_id_info(self):
        await self.check_tokens()
        return self._decode_id_token()

    def get_tokens(self):
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "id_token": self._id_token,
            "expires_at": self._expires_at,
            "updated_at": self._updated_at,
            "guid": self._guid,
        }

    def set_tokens(self, tokens):
        self._access_token = tokens["access_token"]
        self._refresh_token = tokens["refresh_token"]
        self._id_token = tokens["id_token"]
        self._expires_at = tokens["expires_at"]
        self._updated_at = tokens["updated_at"]
        self._guid = tokens["guid"]

    def get_device_id(self):
        if not self._device_id:
            self._device_id = self._generate_new_device_id()
        return self._device_id

    def set_device_id(self, device_id):
        self._device_id = device_id

    def _generate_new_device_id(self):
        return "%030x" % random.randrange(16**64)
