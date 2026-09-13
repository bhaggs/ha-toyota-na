"""The two polling intervals, and the one operation that touches the vehicle.

Kept out of __init__.py so the button platform can reach the wake without
importing the package root, and so the options flow and the coordinator read the
intervals through the same two functions.

The distinction these functions exist to preserve:

  fetch   four GETs for state the cloud already holds. The telematics unit is
          never contacted, so this costs the vehicle nothing.
  poll    wakes the telematics unit and tells it to upload. This is the
          integration's entire 12V battery exposure.
"""
import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FETCH_INTERVAL,
    CONF_POLL_INTERVAL,
    DEFAULT_FETCH_MINUTES,
    DEFAULT_POLL_HOURS,
    REFRESH_SETTLE_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# The poll interval is a staleness floor, not a metronome: it asks that the
# vehicle never go longer than this without being polled, by anything. A button
# press or a service call counts, so an automation that polls on arrival pushes
# the next scheduled poll back rather than being followed by a redundant one.
#
# The two readings only differ when something else polled recently, and in that
# case a scheduled wake buys data the caller already has, at the cost of a real
# 12V wake. Stated in the options form, not left for the user to discover.
POLL_DUE_FRACTION = 0.9

# Per-VIN, because a poll wakes one vehicle. The entry-wide key it replaces
# would, once manual polls started recording, have let polling one car on a
# two-car account defer the scheduled poll of the other.
POLLED_AT = "polled_at"
LEGACY_POLLED_AT = "last_refreshed_at"


def polled_at(entry: ConfigEntry, vin: str) -> float:
    """When this vehicle was last polled, by anything. 0 if never."""
    per_vin = entry.data.get(POLLED_AT) or {}
    if vin in per_vin:
        return per_vin[vin]
    # Entries written before per-VIN tracking carry one entry-wide timestamp.
    # Reading it as every vehicle's last poll errs toward waking less, which is
    # the safe direction, and it self-corrects after the first real poll.
    #
    # Those values were written with datetime.utcnow().timestamp(), which is not
    # an epoch at all - utcnow() is naive, so .timestamp() reads it back as
    # local time and the result is skewed by the UTC offset. That was harmless
    # while the same expression was on both sides of the comparison, but it is
    # not comparable to a real epoch, so a legacy value can be out by up to a
    # day either way. Bounded, one-time, and gone after the first poll.
    return entry.data.get(LEGACY_POLLED_AT) or 0


def poll_due(entry: ConfigEntry, vin: str, poll: timedelta) -> bool:
    """Whether this vehicle is due, given the interval as a staleness floor."""
    since = time.time() - polled_at(entry, vin)
    return since >= poll.total_seconds() * POLL_DUE_FRACTION


def record_polled(hass: HomeAssistant, entry: ConfigEntry, vins: list[str]) -> None:
    """Record a successful poll. Only ever called for vehicles that woke."""
    # time.time(), not datetime.utcnow().timestamp(): the latter is naive and
    # gets read back as local time, so it drifts by an hour at every DST change
    # and a value stored before the change is misread after it.
    now = time.time()
    per_vin = dict(entry.data.get(POLLED_AT) or {})
    per_vin.update({vin: now for vin in vins})
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, POLLED_AT: per_vin}
    )


async def async_poll_now(hass, entry, coordinator, vehicles) -> bool:
    """Wake these vehicles, record it, and re-read once they have uploaded.

    The single path every poll takes - scheduled, button, and service. The
    timestamp write lives here specifically so no caller can forget it, which is
    how the button and the service came to wake the vehicle without deferring
    the next scheduled poll.

    Returns whether anything actually woke. The interval is deliberately not
    consulted: callers that should respect it check before calling, and a
    deliberate press is not a scheduled wake.
    """
    polled = [v.vin for v in vehicles if await async_poll_vehicle(v)]
    if not polled:
        return False

    record_polled(hass, entry, polled)
    # Push what we already hold so the UI reacts immediately, then re-read once
    # the vehicle has had time to upload.
    coordinator.async_set_updated_data(coordinator.data)
    await asyncio.sleep(REFRESH_SETTLE_SECONDS)
    await coordinator.async_request_refresh()
    return True


def _interval(entry: ConfigEntry, key: str, default, unit: str):
    """Read one interval option. Zero, or anything unusable, means never."""
    try:
        value = float(entry.options.get(key, default))
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Ignoring unusable %s option %r; falling back to %s %s",
            key,
            entry.options.get(key),
            default,
            unit,
        )
        value = float(default)
    if value <= 0:
        return None
    return timedelta(**{unit: value})


def fetch_interval(entry: ConfigEntry) -> timedelta | None:
    """How often to re-read the cloud, or None to never do it on a schedule.

    None is a supported value for a DataUpdateCoordinator: it simply never
    schedules itself. Manual refreshes still work.
    """
    return _interval(entry, CONF_FETCH_INTERVAL, DEFAULT_FETCH_MINUTES, "minutes")


def poll_interval(entry: ConfigEntry) -> timedelta | None:
    """How often to wake the vehicle, or None to never wake it on a schedule."""
    return _interval(entry, CONF_POLL_INTERVAL, DEFAULT_POLL_HOURS, "hours")


async def async_poll_vehicle(vehicle) -> bool:
    """Wake one telematics unit and ask it to upload fresh state.

    Returns whether the wake actually went through. Failures are logged and
    swallowed rather than raised: one unreachable vehicle on a multi-car account
    should not stop the others being polled, and a scheduled poll has no user
    waiting on it to report to. Callers that do have a user waiting - the button
    - check the return value and surface it themselves.
    """
    try:
        await vehicle.poll_vehicle_refresh()
    except Exception as e:
        _LOGGER.warning(
            "Could not poll vehicle ...%s (%s); will try again next interval",
            vehicle.vin[-4:],
            e,
        )
        return False
    return True
