"""Brand-aware client for the ctpa-oneapi gateway and its AppSync GraphQL API.

Replaces toyota-na's ToyotaOneClient, which this fork already overrode almost
entirely by assigning replacement methods onto the class at import time. Those
replacements plus the handful of upstream methods that were never overridden
(the generation dispatchers, remote_request_17cy) now live here as one class.
Both sources hardcoded `X-BRAND: "T"`; every brand-scoped header now comes from
self.brand.

The gateway, API keys, GraphQL endpoint, and all endpoint paths are shared
across brands and stay module-level constants.
"""
import json
import logging
from urllib.parse import urlencode, urljoin

import aiohttp

from .auth import OneAuth
from .brands import DEFAULT_BRAND

_LOGGER = logging.getLogger(__name__)

API_GATEWAY = "https://onecdn.telematicsct.com/oneapi/"
GRAPHQL_ENDPOINT = "https://oa-api.telematicsct.com/graphql"
APPSYNC_API_KEY = "da2-zgeayo2qh5eo7cj6pmdwhwugze"
RESOLVER_API_KEY = "pypIHG015k4ABHWbcI4G0a94F7cC0JDo1OynpAsG"
APP_VERSION = "3.4.0"


# --- GraphQL Operations ---

GRAPHQL_PRE_WAKE = """mutation SendPreWakeCommand($guid: String!) {
  postPreWake(guid: $guid) {
    timestamp
    status { messages { responseCode } }
  }
}"""

GRAPHQL_CONFIRM_SUBSCRIPTION = """mutation ConfirmSubscriptionStatus($vin: String!) {
  confirmSubscriptionActive(vin: $vin, payload: {
    vehicleCapabilities: { backdoorType: "hatch" }
  }) { vin }
}"""

GRAPHQL_REFRESH_STATUS = """mutation RefreshVehicleStatus($vin: String!) {
  postRefreshStatus(vin: $vin) {
    payload { correlationId appRequestNo }
    status { messages { responseCode description } }
    timestamp
  }
}"""


class OneClient:
    """API client scoped to one account on one brand."""

    def __init__(self, auth=None, brand=DEFAULT_BRAND):
        self.auth = auth or OneAuth(brand=brand)

    @property
    def brand(self):
        """Brand comes from the auth object so the two can never disagree."""
        return self.auth.brand

    # --- Request plumbing ---

    async def _auth_headers(self):
        return {
            "AUTHORIZATION": "Bearer " + await self.auth.get_access_token(),
            "X-API-KEY": RESOLVER_API_KEY,
            "X-GUID": await self.auth.get_guid(),
            "X-CHANNEL": "ONEAPP",
            "x-region": "US",
            "X-APPVERSION": APP_VERSION,
            "X-LOCALE": "en-US",
            "User-Agent": self.brand.user_agent,
            "Accept": "application/json",
            **self.brand.headers(),
        }

    async def api_request(self, method, endpoint, header_params=None, **kwargs):
        headers = await self._auth_headers()
        if header_params:
            headers.update(header_params)

        endpoint = endpoint.lstrip("/")
        url = urljoin(API_GATEWAY, endpoint)

        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, **kwargs) as resp:
                # Read the body once, before raise_for_status consumes our chance
                # to. Truncated and at debug only: these bodies carry VIN,
                # precise location, and account details, and full-response logs
                # routinely end up pasted into public support threads.
                body = await resp.text()
                if resp.status >= 400:
                    _LOGGER.debug(
                        "API error: %s %s -> %d %s | %s",
                        method,
                        url,
                        resp.status,
                        resp.reason,
                        body[:500],
                    )
                resp.raise_for_status()

        try:
            resp_json = json.loads(body)
        except ValueError:
            _LOGGER.debug("Non-JSON response from %s: %s", url, body[:500])
            raise
        if isinstance(resp_json, dict) and "payload" in resp_json:
            return resp_json["payload"]
        return resp_json

    async def api_get(self, endpoint, header_params=None):
        return await self.api_request("GET", endpoint, header_params)

    async def api_post(self, endpoint, json, header_params=None):
        return await self.api_request("POST", endpoint, header_params, json=json)

    # --- Account and vehicle discovery ---

    async def get_user_vehicle_list(self):
        """List the account's vehicles, bootstrapping only if the list comes back empty.

        Subaru was reported to need GET v4/account before v2/vehicle/guid would
        return anything. Live testing against an active account did not reproduce
        that: discovery worked on a fresh session with no bootstrap at all. The
        likely explanation is that v4/account initializes account state once and
        permanently, so an account that has ever used the SubaruConnect app is
        already initialized - which the reporting accounts may not have been.

        So it is kept, but only as a retry on the empty-list symptom it was
        reported to fix. An already-initialized account pays nothing; a fresh one
        still gets rescued. Best-effort throughout, since a failed bootstrap
        should not take down the config entry.
        """
        vehicles = await self.api_get("v2/vehicle/guid")
        if vehicles or not self.brand.bootstrap_on_empty:
            return vehicles

        _LOGGER.debug(
            "%s returned no vehicles; retrying after account bootstrap",
            self.brand.name,
        )
        try:
            await self.api_get("v4/account")
        except Exception as e:
            _LOGGER.debug("Account bootstrap failed, continuing: %s", e)
        return await self.api_get("v2/vehicle/guid")

    async def get_vehicle_detail(self, vin):
        return await self.api_get("v1/one/vehicle", {"VIN": vin})

    async def get_vehicle_health_report(self, vin):
        return await self.api_get("v1/vehiclehealth/report", {"VIN": vin})

    async def get_vehicle_health_status(self, vin):
        return await self.api_get("v1/vehiclehealth/status", {"VIN": vin})

    async def get_telemetry(self, vin, region="US", generation="17CYPLUS"):
        try:
            return await self.api_get(
                "v2/telemetry",
                {"VIN": vin, "GENERATION": generation, "x-region": region},
            )
        except Exception as e:
            _LOGGER.debug("v2/telemetry failed: %s", e)
            return None

    # --- Generation dispatchers ---

    @staticmethod
    def _unsupported_generation():
        return {"error": {"code": "400", "message": "Unsupported Vehicle Generation"}}

    async def get_vehicle_status(self, vin, generation="17CYPLUS"):
        if generation == "17CY":
            return await self.get_vehicle_status_17cy(vin)
        if generation == "17CYPLUS":
            return await self.get_vehicle_status_17cyplus(vin)
        return self._unsupported_generation()

    async def get_engine_status(self, vin, generation="17CYPLUS"):
        if generation == "17CY":
            return await self.get_engine_status_17cy(vin)
        if generation == "17CYPLUS":
            return await self.get_engine_status_17cyplus(vin)
        return self._unsupported_generation()

    async def send_refresh_status(self, vin, generation="17CYPLUS"):
        if generation == "17CY":
            return await self.send_refresh_request_17cy(vin)
        if generation == "17CYPLUS":
            return await self.send_refresh_request_17cyplus(vin)
        return self._unsupported_generation()

    async def remote_request(self, vin, command, value=None, generation="17CYPLUS"):
        """Send a remote command to the generation-appropriate endpoint.

        17CYPLUS takes a string command: "door-lock", "door-unlock",
        "engine-start", "engine-stop", "hazard-on", "hazard-off",
        "power-window-on", "power-window-off", "ac-settings-on", "sound-horn",
        "buzzer-warning", "find-vehicle", "ventilation-on".

        17CY takes a code and an int value: DL/1 lock, DL/2 unlock, RES/1 engine
        start, RES/2 engine stop, HZ/1 hazards on, HZ/2 hazards off.
        """
        if generation == "17CY":
            return await self.remote_request_17cy(vin, command, value)
        if generation == "17CYPLUS":
            return await self.remote_request_17cyplus(vin, command)
        return self._unsupported_generation()

    # --- 21MM / 24MM / 17CYPLUS ---

    async def get_vehicle_status_17cyplus(self, vin):
        """Doors, locks, windows, hood, and hatch."""
        try:
            res = await self.api_get("v1/global/remote/status", {"VIN": vin, "vin": vin})
            if res and res.get("vehicleStatus"):
                return res
        except Exception as e:
            _LOGGER.debug("v1/global/remote/status failed: %s", e)
        return None

    async def get_engine_status_17cyplus(self, vin):
        try:
            res = await self.api_get(
                "v1/global/remote/engine-status", {"VIN": vin, "vin": vin}
            )
            if res:
                return res
        except Exception as e:
            _LOGGER.debug("v1/global/remote/engine-status failed: %s", e)
        return None

    async def send_refresh_request_17cyplus(self, vin):
        try:
            return await self.api_post(
                "v1/global/remote/refresh-status",
                {
                    "guid": await self.auth.get_guid(),
                    "deviceId": self.auth.get_device_id(),
                    "vin": vin,
                },
                {"VIN": vin},
            )
        except Exception as e:
            _LOGGER.debug("refresh-status failed: %s", e)
        return None

    async def remote_request_17cyplus(self, vin, command):
        return await self.api_post(
            "v1/global/remote/command", {"command": command}, {"VIN": vin}
        )

    # --- 17CY (legacy) ---

    async def get_vehicle_status_17cy(self, vin):
        try:
            return await self.api_get("v2/legacy/remote/status", {"VIN": vin})
        except Exception as e:
            _LOGGER.debug("v2/legacy/remote/status failed: %s", e)
            return None

    async def get_engine_status_17cy(self, vin):
        try:
            return await self.api_get("v1/legacy/remote/engine-status", {"VIN": vin})
        except Exception as e:
            _LOGGER.debug("v1/legacy/remote/engine-status failed: %s", e)
            return None

    async def send_refresh_request_17cy(self, vin):
        try:
            return await self.api_post(
                "v1/legacy/remote/refresh-status",
                {
                    "guid": await self.auth.get_guid(),
                    "deviceId": self.auth.get_device_id(),
                    "deviceType": "Android",
                    "vin": vin,
                },
                {"VIN": vin},
            )
        except Exception as e:
            _LOGGER.debug("v1/legacy/remote/refresh-status failed: %s", e)
            return None

    async def remote_request_17cy(self, vin, command, value):
        return await self.api_post(
            "v1/legacy/remote/command",
            {
                "command": {"code": command, "value": value},
                "guid": await self.auth.get_guid(),
                "deviceId": self.auth.get_device_id(),
                "deviceType": "Android",
                "vin": vin,
            },
            {"VIN": vin},
        )

    # --- Electric / EV ---

    async def get_electric_realtime_status(self, vin, generation="17CYPLUS"):
        try:
            realtime_electric_status = await self.api_post(
                "v2/electric/realtime-status",
                {},
                {"device-id": self.auth.get_device_id(), "vin": vin},
            )
            if generation == "17CYPLUS":
                return await self.get_electric_status(
                    vin, realtime_electric_status["appRequestNo"]
                )
            if realtime_electric_status["returnCode"] == "ONE-RES-10000":
                return await self.get_electric_status(vin)
        except Exception as e:
            _LOGGER.debug("Electric realtime status failed: %s", e)
            return None

    async def get_electric_status(self, vin, realtime_status=None):
        try:
            url = "v2/electric/status"
            if realtime_status:
                url += "?" + urlencode({"realtime-status": realtime_status})

            electric_status = await self.api_get(url, {"VIN": vin})
            if "vehicleInfo" in electric_status:
                return electric_status
        except Exception as e:
            _LOGGER.debug("Electric status failed: %s", e)
            return None

    # --- GraphQL (AppSync) ---

    async def graphql_request(self, operation_name, query, variables):
        headers = {
            "Content-Type": "application/json",
            "x-api-key": APPSYNC_API_KEY,
            "x-resolver-api-key": RESOLVER_API_KEY,
            "Authorization": "Bearer " + await self.auth.get_access_token(),
            "vin": variables.get("vin", ""),
            "x-guid": await self.auth.get_guid(),
            "x-deviceid": self.auth.get_device_id(),
            "x-channel": "ONEAPP",
            "X-APPVERSION": APP_VERSION,
            "X-OSNAME": "Android",
            "X-OSVERSION": "14",
            "X-LOCALE": "en-US",
            "User-Agent": self.brand.user_agent,
            **self.brand.headers(),
        }
        payload = json.dumps(
            {
                "operationName": operation_name,
                "query": query,
                "variables": variables,
            }
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GRAPHQL_ENDPOINT, headers=headers, data=payload
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    _LOGGER.debug(
                        "GraphQL %s error: HTTP %d: %s",
                        operation_name,
                        resp.status,
                        body[:500],
                    )
                    return None
                result = json.loads(body)
                if result.get("errors"):
                    err = result["errors"][0]
                    _LOGGER.debug(
                        "GraphQL %s error: %s: %s",
                        operation_name,
                        err.get("errorType"),
                        err.get("message"),
                    )
                    return None
                return result.get("data")

    async def graphql_pre_wake(self, guid):
        """Wake the vehicle's telematics unit so it will answer a status request."""
        return await self.graphql_request(
            "SendPreWakeCommand", GRAPHQL_PRE_WAKE, {"guid": guid}
        )

    async def graphql_confirm_subscription(self, vin):
        return await self.graphql_request(
            "ConfirmSubscriptionStatus", GRAPHQL_CONFIRM_SUBSCRIPTION, {"vin": vin}
        )

    async def graphql_refresh_status(self, vin):
        """Ask the vehicle to upload fresh status."""
        return await self.graphql_request(
            "RefreshVehicleStatus", GRAPHQL_REFRESH_STATUS, {"vin": vin}
        )
