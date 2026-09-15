"""Buttons for the one-shot remote commands.

These commands have always been available as services, but a service has no
entity behind it, so nothing appeared on the device page except the lock. These
buttons expose the same actions as entities. The services stay registered, so
existing automations and scripts are unaffected.
"""
import logging
from typing import Any

from toyota_na.vehicle.base_vehicle import ApiVehicleGeneration, ToyotaVehicle

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .base_entity import ToyotaNABaseEntity
from .const import (
    BUTTONS,
    COMMAND_MAP,
    CY17PLUS_ONLY_ACTIONS,
    DOMAIN,
    POLL_VEHICLE,
    REFRESH,
)
from .polling import async_poll_now

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Set up the button platform."""
    buttons = []

    coordinator: DataUpdateCoordinator[list[ToyotaVehicle]] = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]

    for vehicle in coordinator.data:
        # The legacy 17CY protocol sends a different command/value pair and has
        # no equivalent for the buzzer or lights, so send_command would raise on
        # press. Leave those buttons off rather than offer a broken control.
        legacy = vehicle.generation == ApiVehicleGeneration.CY17
        for button in BUTTONS:
            if legacy and button["action"] in CY17PLUS_ONLY_ACTIONS:
                continue
            # Almost all of these need a remote subscription; without one the
            # command would be refused, so offering the button would mislead.
            # Refresh is the exception - it only re-reads the cloud.
            if button.get("subscription", True) and vehicle.subscribed is False:
                continue
            buttons.append(
                ToyotaButton(
                    button["action"],
                    button["icon"],
                    coordinator,
                    button["key"],
                    button["name"],
                    vehicle.vin,
                )
            )

    async_add_devices(buttons)


class ToyotaButton(ToyotaNABaseEntity, ButtonEntity):
    """A single remote command."""

    def __init__(self, action: str, icon: str, *args: Any):
        super().__init__(*args)
        self._action = action
        self._icon = icon

    @property
    def icon(self) -> str:
        return self._icon

    async def async_press(self) -> None:
        # Refresh touches only the cloud, so it needs neither a reachable
        # vehicle object nor a subscription. Handled before those checks.
        if self._action == REFRESH:
            # Credit the press if the refresh brings a new report. Held on the
            # coordinator, because the refresh is debounced and may run late.
            self.coordinator.async_set_cause([self.vin], self._context)
            await self.coordinator.async_request_refresh()
            return

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
            if self._action == POLL_VEHICLE:
                await self._poll_vehicle(vehicle)
            else:
                await vehicle.send_command(COMMAND_MAP[self._action])
        except HomeAssistantError:
            raise
        except Exception as e:
            # Surface it in the UI rather than only in the log: the user pressed
            # a button and deserves to know the car never got the command. These
            # are undocumented endpoints, so failures are not unexpected.
            _LOGGER.debug("%s failed for ...%s: %s", self._action, self.vin[-4:], e)
            raise HomeAssistantError(f"{self._attr_name} failed: {e}") from e

    async def _poll_vehicle(self, vehicle) -> None:
        """Wake the vehicle for fresh state, then re-read once it has settled.

        A deliberate press is not a scheduled poll, so the interval is not
        consulted. The poll is still recorded, so pressing this defers the next
        scheduled poll rather than being followed by a redundant one.
        """
        # async_poll_now swallows the failure so a multi-vehicle poll can carry
        # on to the next car. Here someone is watching, so say so.
        if not await async_poll_now(
            self.hass,
            self.coordinator.config_entry,
            self.coordinator,
            [vehicle],
            context=self._context,
        ):
            raise HomeAssistantError(
                f"{self._attr_name}: the vehicle's servers did not accept the "
                "request, often because they are rate-limiting polls. Try again "
                "later; the log says exactly why."
            )
