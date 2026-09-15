"""Describe this integration's events for Home Assistant's Activity views.

Both events exist so Activity details, added in Home Assistant 2026.9, can name a
cause for an update nothing else started. Where a person or an automation did
start it, their own context is passed through instead, and Home Assistant
already knows how to describe that. See coordinator.py and
bhaggs/ha-toyota-na#10.

The name is what the dialog shows as the cause, so it names the cause rather
than the vehicle.
"""
from collections.abc import Callable

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, EVENT_VEHICLE_POLLED, EVENT_VEHICLE_REPORT


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict]], None],
) -> None:
    """Describe logbook events."""

    def _vehicle_name(event: Event) -> str:
        # The event carries a device id and nothing else, so the name is looked
        # up here - which also means it follows a rename in the UI.
        device_id = event.data.get(ATTR_DEVICE_ID)
        device = dr.async_get(hass).async_get(device_id) if device_id else None
        if device is None:
            return "the vehicle"
        return device.name_by_user or device.name or "the vehicle"

    @callback
    def async_describe_polled(event: Event) -> dict[str, str]:
        return {
            LOGBOOK_ENTRY_NAME: "Scheduled vehicle poll",
            LOGBOOK_ENTRY_MESSAGE: f"woke {_vehicle_name(event)}",
        }

    @callback
    def async_describe_report(event: Event) -> dict[str, str]:
        # "Picked up", never a reason. The gateway says that the vehicle sent a
        # report, not why - after a drive and after the Subaru app asked for one
        # look exactly the same from here.
        return {
            LOGBOOK_ENTRY_NAME: "New report from the vehicle",
            LOGBOOK_ENTRY_MESSAGE: f"picked up for {_vehicle_name(event)}",
        }

    async_describe_event(DOMAIN, EVENT_VEHICLE_POLLED, async_describe_polled)
    async_describe_event(DOMAIN, EVENT_VEHICLE_REPORT, async_describe_report)
