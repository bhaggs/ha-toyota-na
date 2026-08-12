"""Remote start as a switch rather than a pair of buttons.

Remote start is stateful - the vehicle reports whether it is currently running,
and for how much longer - so a switch models it better than two buttons that
throw that state away. Adapted from the approach in widewing/ha-toyota-na#182,
which observed that Home Assistant's Alexa and Google integrations expect
stateful start/stop features to be switches.

On an EV this is climate preconditioning rather than an engine, but the backend
command and the existing service are both named for the ICE behaviour.
"""
import asyncio
import logging
from typing import Any

from toyota_na.vehicle.base_vehicle import ToyotaVehicle, VehicleFeatures
from toyota_na.vehicle.entity_types.ToyotaRemoteStart import ToyotaRemoteStart

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .base_entity import ToyotaNABaseEntity
from .const import COMMAND_MAP, DOMAIN, ENGINE_START, ENGINE_STOP

_LOGGER = logging.getLogger(__name__)

# The vehicle takes a moment to report a start, so wait before re-polling
# rather than immediately reading back a state we know is stale.
COMMAND_SETTLE_SECONDS = 10


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Set up the switch platform."""
    switches = []

    coordinator: DataUpdateCoordinator[list[ToyotaVehicle]] = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]

    for vehicle in coordinator.data:
        if vehicle.subscribed is False:
            continue
        switches.append(
            ToyotaRemoteStartSwitch(
                coordinator, "remote_start", "Remote start", vehicle.vin
            )
        )

    async_add_devices(switches)


class ToyotaRemoteStartSwitch(ToyotaNABaseEntity, SwitchEntity):
    """Start and stop remote climate/engine operation."""

    _attr_icon = "mdi:car-clock"

    def __init__(self, *args: Any):
        super().__init__(*args)
        # Bridges the gap between sending a command and the vehicle reporting
        # it. Deliberately cleared on the next poll rather than held: if the
        # command silently failed, the switch should tell the truth rather than
        # keep showing what we asked for. See the hazards discussion in #182 -
        # optimistic state that can never be corrected is worse than none.
        self._optimistic: bool | None = None

    @property
    def _reported(self) -> bool | None:
        feature = self.feature(VehicleFeatures.RemoteStartStatus)
        if isinstance(feature, ToyotaRemoteStart):
            return feature.on
        return None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic is not None:
            return self._optimistic
        return self._reported

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Runtime detail the vehicle reports alongside the on/off state."""
        feature = self.feature(VehicleFeatures.RemoteStartStatus)
        if not isinstance(feature, ToyotaRemoteStart):
            return None
        attributes = {
            "start_time": feature.start_time,
            "end_time": feature.end_time,
            "minutes_remaining": feature.time_left,
            "total_runtime": feature.timer,
        }
        return {k: v for k, v in attributes.items() if v is not None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(ENGINE_START, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(ENGINE_STOP, False)

    async def _send(self, action: str, optimistic: bool) -> None:
        vehicle = self.vehicle
        if vehicle is None:
            raise HomeAssistantError(
                f"{self._attr_name}: vehicle is not currently available"
            )
        if not vehicle.subscribed:
            raise HomeAssistantError(
                f"{self._attr_name}: requires an active remote services subscription"
            )

        try:
            await vehicle.send_command(COMMAND_MAP[action])
        except Exception as e:
            _LOGGER.debug("%s failed for ...%s: %s", action, self.vin[-4:], e)
            raise HomeAssistantError(f"{self._attr_name} failed: {e}") from e

        self._optimistic = optimistic
        self.async_write_ha_state()
        await asyncio.sleep(COMMAND_SETTLE_SECONDS)
        await self.coordinator.async_request_refresh()

    def _handle_coordinator_update(self) -> None:
        # Whatever the vehicle now reports supersedes what we asked for.
        self._optimistic = None
        super()._handle_coordinator_update()
