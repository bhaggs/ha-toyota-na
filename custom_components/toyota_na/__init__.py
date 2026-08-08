from datetime import timedelta, datetime
import logging
import asyncio

from .oneapi import OneAuth, OneClient, get_brand

# Patch base_vehicle
import toyota_na.vehicle.base_vehicle
from .patch_base_vehicle import ApiVehicleGeneration
toyota_na.vehicle.base_vehicle.ApiVehicleGeneration = ApiVehicleGeneration
from .patch_base_vehicle import VehicleFeatures
toyota_na.vehicle.base_vehicle.VehicleFeatures = VehicleFeatures
from .patch_base_vehicle import RemoteRequestCommand
toyota_na.vehicle.base_vehicle.RemoteRequestCommand = RemoteRequestCommand
from .patch_base_vehicle import ToyotaVehicle
toyota_na.vehicle.base_vehicle.ToyotaVehicle = ToyotaVehicle

# Patch seventeen_cy_plus
from toyota_na.vehicle.vehicle_generations.seventeen_cy_plus import SeventeenCYPlusToyotaVehicle
from .patch_seventeen_cy_plus import SeventeenCYPlusToyotaVehicle
toyota_na.vehicle.vehicle_generations.seventeen_cy_plus.SeventeenCYPlusToyotaVehicle = SeventeenCYPlusToyotaVehicle

# Patch seventeen_cy
from toyota_na.vehicle.vehicle_generations.seventeen_cy import SeventeenCYToyotaVehicle
from .patch_seventeen_cy import SeventeenCYToyotaVehicle
toyota_na.vehicle.vehicle_generations.seventeen_cy.SeventeenCYToyotaVehicle = SeventeenCYToyotaVehicle

from toyota_na.exceptions import AuthError
from toyota_na.vehicle.base_vehicle import RemoteRequestCommand, ToyotaVehicle

#Patch get_vehicles
from .patch_vehicle import get_vehicles
#from toyota_na.vehicle.vehicle import get_vehicles

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, service
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .websocket_handler import ToyotaWebSocketHandler

from .const import (
    BRAND,
    COMMAND_MAP,
    DOMAIN,
    ENGINE_START,
    ENGINE_STOP,
    HAZARDS_ON,
    HAZARDS_OFF,
    DOOR_LOCK,
    DOOR_UNLOCK,
    REFRESH,
    UPDATE_INTERVAL,
    REFRESH_STATUS_INTERVAL
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["binary_sensor", "device_tracker", "lock", "sensor"]

async def async_setup(hass: HomeAssistant, _processed_config) -> bool:
    @service.verify_domain_control(DOMAIN)
    async def async_service_handle(service_call: ServiceCall) -> None:
        """Handle dispatched services."""

        device_registry = dr.async_get(hass)
        device = device_registry.async_get(service_call.data["vehicle"])
        remote_action = service_call.service

        if device is None:
            _LOGGER.warning("Device does not exist")
            return

        # There is currently not a case with this integration where
        # the device will have more or less than one config entry
        if len(device.config_entries) == 0:
            _LOGGER.warning("Device missing config entry")
            return

        for entry_id in device.config_entries:
            if entry_id not in hass.data[DOMAIN]:
                _LOGGER.warning("Config entry not found")
                continue

            if "coordinator" not in hass.data[DOMAIN][entry_id]:
                _LOGGER.warning("Coordinator not found")
                continue

            coordinator = hass.data[DOMAIN][entry_id]["coordinator"]
            if coordinator.data is None:
                _LOGGER.warning("No coordinator data")

        if coordinator.data is None:
            _LOGGER.warning("No coordinator data")
            return

        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:

                vin = identifier[1]
                for vehicle in coordinator.data:
                    if vehicle.vin == vin and remote_action.upper() == "REFRESH" and vehicle.subscribed:
                        await vehicle.poll_vehicle_refresh()
                        # TODO: This works great and prevents us from unnecessarily hitting Toyota. But we can and should
                        # probably do stuff like this in the library where we can better control which APIs we hit to refresh our in-memory data.
                        coordinator.async_set_updated_data(coordinator.data)
                        await asyncio.sleep(10)
                        await coordinator.async_request_refresh()
                    elif vehicle.vin == vin and vehicle.subscribed:
                        await vehicle.send_command(COMMAND_MAP[remote_action])
                        break

                # Masked: HA logs at INFO by default and these get pasted into
                # public support threads. Last 4 is enough to tell cars apart.
                _LOGGER.info(
                    "Handling service call %s for vehicle ...%s", remote_action, vin[-4:]
                )

        return

    hass.services.async_register(DOMAIN, ENGINE_START, async_service_handle)
    hass.services.async_register(DOMAIN, ENGINE_STOP, async_service_handle)
    hass.services.async_register(DOMAIN, HAZARDS_ON, async_service_handle)
    hass.services.async_register(DOMAIN, HAZARDS_OFF, async_service_handle)
    hass.services.async_register(DOMAIN, DOOR_LOCK, async_service_handle)
    hass.services.async_register(DOMAIN, DOOR_UNLOCK, async_service_handle)
    hass.services.async_register(DOMAIN, REFRESH, async_service_handle)

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})

    # Entries created before brand support existed have no BRAND key; they are
    # Toyota, and get_brand defaults accordingly.
    brand = get_brand(entry.data.get(BRAND))

    client = OneClient(
        OneAuth(
            brand=brand,
            initial_tokens=entry.data["tokens"],
            callback=lambda tokens: update_tokens(tokens, hass, entry),
        )
    )
    try:
        await client.auth.check_tokens()
    except AuthError as e:
        _LOGGER.debug("Stored tokens rejected for %s: %s", brand.name, e)
        raise ConfigEntryAuthFailed(e) from e

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=lambda: update_vehicles_status(hass, client, entry),
        update_interval=timedelta(seconds=UPDATE_INTERVAL),
    )
    # Entities read this for the device-registry manufacturer. Attached here
    # rather than passed through every platform's entity constructor, which
    # would mean touching all four platforms for one string.
    coordinator.brand = brand

    await coordinator.async_config_entry_first_refresh()

    # Start WebSocket handler for vehicle status push notifications (21MM+)
    ws_handler = ToyotaWebSocketHandler(client)
    vins = [v.vin for v in coordinator.data if v.subscribed] if coordinator.data else []
    if vins:
        await ws_handler.start(vins)
    client._ws_handler = ws_handler

    hass.data[DOMAIN][entry.entry_id] = {
        "toyota_na_client": client,
        "coordinator": coordinator,
        "ws_handler": ws_handler,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


def update_tokens(tokens: dict[str, str], hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.info("Tokens refreshed, updating ConfigEntry")
    data = dict(entry.data)
    data["tokens"] = tokens
    hass.config_entries.async_update_entry(entry, data=data)


async def update_vehicles_status(hass: HomeAssistant, client: OneClient, entry: ConfigEntry):
    need_refresh = False
    need_refresh_before = datetime.utcnow().timestamp() - REFRESH_STATUS_INTERVAL
    if "last_refreshed_at" not in entry.data or entry.data["last_refreshed_at"] < need_refresh_before:
        need_refresh = True
    try:
        _LOGGER.debug("Updating vehicle status")
        raw_vehicles = await get_vehicles(client)
        if not raw_vehicles:
            # These are undocumented, reverse-engineered endpoints on a service
            # that changes without notice. An empty list usually means a new
            # required header or a stale session, not a vanished car - so leave
            # the entry loaded and try again next interval rather than failing
            # setup and forcing the user to reconfigure.
            _LOGGER.warning(
                "%s returned no vehicles. If this persists, the backend may have "
                "changed; run scripts/validate_brand.py to diagnose.",
                client.brand.name,
            )
            return []
        vehicles: list[ToyotaVehicle] = []
        for vehicle in raw_vehicles:
            if vehicle.subscribed is not True:
                _LOGGER.warning(
                    f"Your {vehicle.model_year} {vehicle.model_name} needs a remote services subscription to fully work with Home Assistant."
                )
            if need_refresh and vehicle.subscribed:
                try:
                    _LOGGER.info(
                        "Requesting vehicle refresh for %s %s",
                        vehicle.model_year,
                        vehicle.model_name,
                    )
                    await vehicle.poll_vehicle_refresh()
                except Exception as e:
                    _LOGGER.warning("Vehicle refresh failed (%s), continuing without refresh", e)
            vehicles.append(vehicle)
        entry_data = dict(entry.data)
        if need_refresh:
            entry_data["last_refreshed_at"] = datetime.utcnow().timestamp()
        hass.config_entries.async_update_entry(entry, data=entry_data)
        return vehicles
    except AuthError as e:
        # Hand off to Home Assistant's reauth flow rather than retrying the
        # stored password on a loop. Login now needs an OTP the integration
        # cannot supply unattended, and repeatedly replaying bad credentials
        # risks the account being locked.
        _LOGGER.debug("Authentication failed, requesting reauth: %s", e)
        raise ConfigEntryAuthFailed(e) from e
    except Exception as e:
        _LOGGER.exception("Error fetching data")
        raise UpdateFailed(e) from e


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # Stop WebSocket handler
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    ws_handler = entry_data.get("ws_handler")
    if ws_handler:
        await ws_handler.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
