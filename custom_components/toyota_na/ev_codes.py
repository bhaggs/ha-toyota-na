"""Decoding for the EV charge-status integer codes.

The gateway reports charging state as bare integers with no accompanying
vocabulary. Mappings here are empirical - established by correlating readings
against observed vehicle state - so anything unrecognised is passed through
unchanged rather than guessed at or hidden.

Deliberately free of Home Assistant imports so the vehicle parsers can use it
without pulling the entity layer in.
"""
import logging

_LOGGER = logging.getLogger(__name__)

_REPORTED_UNKNOWN = set()

CONNECTOR_STATUS = {
    2: "Disconnected",
    4: "Unlocked",
    5: "Locked",
}
"""Connector latch state.

From widewing/ha-toyota-na#181, and corroborated on a 2026 Solterra: 5 while
charging, 2 with the cable removed. Note "Locked" describes the latch, not
charging as such - the connector stays latched while plugged in and live.
"""

CONNECTOR_STATUS_CHARGING = 5
"""The value the charging binary sensor is derived from."""


PLUG_STATUS = {
    12: "Unplugged",
    36: "Plugged in",
    40: "Charging",
    45: "Charging ended",
    56: "DC charging",
    60: "DC charging",
}
"""Charge port state.

From widewing/ha-toyota-na#86, where 12/40/45 were reported, @dovecode added 36
for a plugged-in vehicle waiting on a charge schedule, and 56 and 60 were both
seen at a DC fast charger - 56 with Plug & Charge, 60 with an app-started
session. They share a label because the distinction is how the session was
authorized, not what the vehicle is doing.

Corroborated on a Solterra: 40 through a Level 1 session, 12 unplugged.

45 is labelled "Charging ended" rather than #86's "Done Charging but plugged in".
Cutting power to the EVSE mid-session also produced 45, so the code does not
distinguish a full battery from an interrupted session, and a label implying it
charged to full would be asserting more than the value carries.

The values look like packed flags rather than a flat enum: 32 is set on every
plugged state and clear only on 12, and 16 is set only on the two DC readings.
Six samples is not enough to decode the rest, so they are treated as an enum for
now and unknown codes pass through unchanged.
"""

UNAVAILABLE_UINT16 = 65535
"""0xFFFF, the "not applicable" sentinel for 16-bit fields.

Observed on a Solterra: remainingChargeTime reads 65535 while unplugged. Taken
at face value it renders as a real reading - 45 days or 18 hours depending on
the unit - and would poison any statistics derived from it.
"""


def numeric(value):
    """Numeric reading with the not-applicable sentinel turned into None.

    None reaches Home Assistant as "unknown", which is what an inapplicable
    reading should look like.
    """
    if value is None:
        return None
    try:
        if int(value) == UNAVAILABLE_UINT16:
            return None
    except (TypeError, ValueError):
        pass
    return value


def decode(value, table, field="code"):
    """Look up a code, tolerating the string digits the API sometimes returns.

    Unknown codes come back untouched, so a new value shows up in the UI as
    itself rather than as "unknown", and it is logged once so it is noticed
    without having to be watching that entity at the time. These mappings were
    all built from observations like that.
    """
    if value is None:
        return None
    key = value
    if not isinstance(key, int):
        text = str(key).strip()
        if text.lstrip("-").isdigit():
            key = int(text)
    if key in table:
        return table[key]

    # Once per distinct value: the coordinator polls every 10 minutes, and a
    # vehicle can sit in one state for days.
    marker = (field, key)
    if marker not in _REPORTED_UNKNOWN:
        _REPORTED_UNKNOWN.add(marker)
        _LOGGER.info(
            "Unrecognised %s value %r from the vehicle. Known values are %s. "
            "Please report it at https://github.com/bhaggs/ha-toyota-na/issues/3",
            field,
            value,
            sorted(table),
        )
    return value


def connector_status(value):
    """Human-readable connector latch state."""
    return decode(value, CONNECTOR_STATUS, "connector status")


def plug_status(value):
    """Human-readable charge port state."""
    return decode(value, PLUG_STATUS, "plug status")
