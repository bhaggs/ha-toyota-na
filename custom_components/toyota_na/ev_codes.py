"""Decoding for the EV charge-status integer codes.

The gateway reports charging state as bare integers with no accompanying
vocabulary. Mappings here are empirical - established by correlating readings
against observed vehicle state - so anything unrecognised is passed through
unchanged rather than guessed at or hidden.

Deliberately free of Home Assistant imports so the vehicle parsers can use it
without pulling the entity layer in.
"""

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


def decode(value, table):
    """Look up a code, tolerating the string digits the API sometimes returns.

    Unknown codes come back untouched, so a new value shows up in the UI as
    itself rather than as "unknown" - which is what makes the next one
    discoverable.
    """
    if value is None:
        return None
    key = value
    if not isinstance(key, int):
        text = str(key).strip()
        if text.lstrip("-").isdigit():
            key = int(text)
    return table.get(key, value)


def connector_status(value):
    """Human-readable connector latch state."""
    return decode(value, CONNECTOR_STATUS)
