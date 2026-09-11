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
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_FETCH_INTERVAL,
    CONF_POLL_INTERVAL,
    DEFAULT_FETCH_MINUTES,
    DEFAULT_POLL_HOURS,
)

_LOGGER = logging.getLogger(__name__)

# A scheduled poll is skipped if the previous one was more recent than this
# fraction of the interval. async_track_time_interval re-arms from zero at
# setup, so without the check a user restarting Home Assistant hourly would wake
# the vehicle hourly whatever the interval says. Below 1.0 so ordinary timer
# jitter can never cause a legitimate poll to be skipped.
POLL_DUE_FRACTION = 0.9


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
