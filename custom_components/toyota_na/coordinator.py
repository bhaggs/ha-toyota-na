"""A coordinator that keeps track of why each update happened.

Home Assistant 2026.9's Activity details dialog explains a state change by
following its context back to where it started. None of this integration's
writes carried one, so every change read "No cause was recorded for this
activity". See bhaggs/ha-toyota-na#10.

Two things make that harder than setting a context before asking for a refresh:

- An entity only keeps a context for five seconds after it is set
  (CONTEXT_RECENT_TIME_SECONDS), and a poll waits ten before re-reading the
  vehicle. A context attached when a button is pressed has always expired by
  the time the new data arrives. So the context is held here, and each entity
  applies it at the moment it writes - see ToyotaNABaseEntity.
- Refreshes are debounced. One requested after a poll can run late, and an
  unrelated scheduled refresh can get there first, before the vehicle has
  uploaded anything. So a cause is not handed to "the next refresh". It waits
  for the refresh in which that vehicle's own report time actually moves, and
  lapses if none does within CAUSE_TTL_SECONDS.

Where nothing started an update - a scheduled poll, or the regular refresh
noticing a report the vehicle made on its own - the integration fires one of its
own events and uses that as the cause. Those are described in logbook.py.
"""
import time

from toyota_na.vehicle.base_vehicle import ToyotaVehicle, VehicleFeatures

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, EVENT_VEHICLE_POLLED, EVENT_VEHICLE_REPORT

# Long enough to outlast the settle delay, a debounced refresh and a slow
# gateway. Short enough that a press cannot be credited with a report the
# vehicle makes on its own much later.
CAUSE_TTL_SECONDS = 120

# A cause is only credited with a report made after it was set. The report time
# comes from the vehicle and the gateway rather than this machine's clock, so
# allow them to disagree by this much.
REPORT_CLOCK_SLACK_SECONDS = 60


@callback
def async_fire_cause(
    hass: HomeAssistant, config_entry_id: str, event_type: str, vin: str
) -> Context:
    """Fire one of this integration's events and return its context.

    Only for updates nothing else started. Where a person or automation did,
    their context is used instead, and Home Assistant already describes it.

    The event carries the device id and nothing else. Event data is written to
    the recorder, and a VIN has no business there.
    """
    context = Context()
    data = {}
    # Looked up within this config entry. async_get_device is deprecated from
    # Home Assistant 2026.9 and breaks in 2027.8, because identifiers are no
    # longer unique across config entries; the entry is what makes this lookup
    # unambiguous. It arrived in 2026.8, which is why hacs.json requires that.
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, vin), config_entry_id
    )
    if device is not None:
        data[ATTR_DEVICE_ID] = device.id
    hass.bus.async_fire(event_type, data, context=context)
    return context


def _report_time(vehicle: ToyotaVehicle) -> float | None:
    """When the vehicle made the report this data came from, as an epoch."""
    value = getattr(vehicle.features.get(VehicleFeatures.LastTimeStamp), "value", None)
    return value if isinstance(value, (int, float)) else None


class ToyotaCoordinator(DataUpdateCoordinator[list[ToyotaVehicle]]):
    """A DataUpdateCoordinator that also works out why each update happened."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # vin -> (context, when it was set): a cause waiting for its report.
        self.pending_causes: dict[str, tuple[Context, float]] = {}
        # vin -> context for the dispatch in progress. Read by
        # ToyotaNABaseEntity, and emptied as soon as that dispatch is done.
        self.update_contexts: dict[str, Context] = {}
        # vin -> the report time last seen. Kept here rather than read off the
        # previous data, because a poll parses part of its response straight
        # into the vehicle objects already held: by the time the next refresh
        # runs, "before" would already contain the new values.
        self._report_times: dict[str, float] = {}

    @callback
    def async_set_cause(self, vins: list[str], context: Context | None) -> None:
        """Credit `context` with the next new report from these vehicles."""
        if context is None:
            return
        now = time.time()
        for vin in vins:
            self.pending_causes[vin] = (context, now)

    @callback
    def async_vehicles_polled(
        self, vins: list[str], context: Context | None, *, scheduled: bool = False
    ) -> None:
        """Record the cause of a poll that just woke these vehicles.

        Applied to the dispatch that follows straight away, as well as held for
        the report. A poll parses part of its response directly into the vehicle
        objects, and async_poll_now pushes that out immediately - before the
        follow-up refresh ever runs - so without this, those writes would carry
        no cause at all.
        """
        for vin in vins:
            cause = (
                async_fire_cause(self.hass, self.config_entry.entry_id, EVENT_VEHICLE_POLLED, vin)
                if scheduled
                else context
            )
            if cause is None:
                continue
            self.async_set_cause([vin], cause)
            self.update_contexts[vin] = cause

    async def _async_update_data(self) -> list[ToyotaVehicle]:
        # Nothing left over from a dispatch that never happened may leak into
        # this one.
        self.update_contexts = {}
        vehicles = await super()._async_update_data()
        self._async_resolve_causes(vehicles)
        return vehicles

    @callback
    def _async_resolve_causes(self, vehicles: list[ToyotaVehicle] | None) -> None:
        now = time.time()
        for vehicle in vehicles or []:
            reported = _report_time(vehicle)
            if reported is None:
                # Without a report time there is no telling a new report from an
                # old one, so this vehicle stays as it was: uncaused.
                continue
            previous = self._report_times.get(vehicle.vin)
            self._report_times[vehicle.vin] = reported
            if previous is None or reported <= previous:
                # First sight of this vehicle - loading the integration is not a
                # vehicle report - or nothing new since the last refresh.
                continue
            self.update_contexts[vehicle.vin] = self._async_cause_for(
                vehicle.vin, reported, now
            )

        # A cause still waiting past its window was never answered.
        for vin, (_, set_at) in list(self.pending_causes.items()):
            if now - set_at > CAUSE_TTL_SECONDS:
                del self.pending_causes[vin]

    @callback
    def _async_cause_for(self, vin: str, reported: float, now: float) -> Context:
        pending = self.pending_causes.get(vin)
        if pending is not None:
            context, set_at = pending
            if (
                now - set_at <= CAUSE_TTL_SECONDS
                and reported >= set_at - REPORT_CLOCK_SLACK_SECONDS
            ):
                del self.pending_causes[vin]
                return context
            # A report from before this cause was set was not caused by it. Leave
            # the cause waiting for the report it did cause.
        return async_fire_cause(self.hass, self.config_entry.entry_id, EVENT_VEHICLE_REPORT, vin)

    @callback
    def async_update_listeners(self) -> None:
        try:
            super().async_update_listeners()
        finally:
            self.update_contexts = {}
