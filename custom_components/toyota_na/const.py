from toyota_na.vehicle.base_vehicle import VehicleFeatures

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfPressure,
)

from toyota_na.vehicle.base_vehicle import RemoteRequestCommand


DOMAIN = "toyota_na"

BRAND = "brand"
"""Config entry key holding the brand code. Absent on pre-Subaru entries."""

DOOR_LOCK = "door_lock"
DOOR_UNLOCK = "door_unlock"
ENGINE_START = "engine_start"
ENGINE_STOP = "engine_stop"
HAZARDS_ON = "hazards_on"
HAZARDS_OFF = "hazards_off"
REFRESH = "refresh"
BUZZER = "buzzer"
LIGHTS_ON = "lights_on"
LIGHTS_OFF = "lights_off"

UPDATE_INTERVAL = 600
REFRESH_STATUS_INTERVAL = 2 * 3600

COMMAND_MAP = {
    DOOR_LOCK: RemoteRequestCommand.DoorLock,
    DOOR_UNLOCK: RemoteRequestCommand.DoorUnlock,
    ENGINE_START: RemoteRequestCommand.EngineStart,
    ENGINE_STOP: RemoteRequestCommand.EngineStop,
    HAZARDS_ON: RemoteRequestCommand.HazardsOn,
    HAZARDS_OFF: RemoteRequestCommand.HazardsOff,
    REFRESH: RemoteRequestCommand.Refresh,
    BUZZER: RemoteRequestCommand.BuzzerWarning,
    LIGHTS_ON: RemoteRequestCommand.LightsOn,
    LIGHTS_OFF: RemoteRequestCommand.LightsOff,
}

# Commands the legacy 17CY protocol has no equivalent for. Buttons for these are
# not created on those vehicles, since send_command would raise on press.
CY17PLUS_ONLY_ACTIONS = {BUZZER, LIGHTS_ON, LIGHTS_OFF}

SEND_COMMAND = "send_command"

# One-shot remote commands. Buttons suit these because they are stateless: the
# vehicle reports nothing to read back afterwards. Remote start is deliberately
# not here - it is stateful, so it lives in switch.py.
#
# All of them require a remote subscription, so buttons are only created for
# subscribed vehicles, matching how lock.py handles it.
BUTTONS = [
    {
        # One button, not a pair. The hazards are momentary: they auto-off after
        # roughly a minute, and hazard-off was measured to have no observable
        # effect on a real vehicle. Toyota's own app offers no manual off either,
        # and SubaruConnect shows a single hazards control. The hazards_off
        # service is still registered for automations - it has never been proven
        # broken everywhere, only never proven working.
        "action": HAZARDS_ON,
        "icon": "mdi:hazard-lights",
        "name": "Hazards",
    },
    {
        "action": BUZZER,
        "icon": "mdi:bullhorn",
        "name": "Buzzer",
    },
    {
        "action": REFRESH,
        "icon": "mdi:refresh",
        # Unlike the others this wakes the telematics unit to upload fresh
        # state, so it draws on the 12V battery. See issue #2.
        "name": "Refresh Data",
    },
]

BINARY_SENSORS = [
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.FrontDriverDoor,
        "icon": "mdi:car-door",
        "name": "Front Driver Door",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.FrontPassengerDoor,
        "icon": "mdi:car-door",
        "name": "Front Passenger Door",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.RearDriverDoor,
        "icon": "mdi:car-door",
        "name": "Rear Driver Door",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.RearPassengerDoor,
        "icon": "mdi:car-door",
        "name": "Rear Passenger Door",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.Hood,
        "icon": "mdi:car-door",
        "name": "Hood",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.Trunk,
        "icon": "mdi:car-door",
        "name": "Trunk",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.Moonroof,
        "icon": "mdi:window-closed-variant",
        "name": "Moonroof",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.FrontDriverWindow,
        "icon": "mdi:window-closed-variant",
        "name": "Front Driver Window",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.FrontPassengerWindow,
        "icon": "mdi:window-closed-variant",
        "name": "Front Passenger Window",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.RearDriverWindow,
        "icon": "mdi:window-closed-variant",
        "name": "Rear Driver Window",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.RearPassengerWindow,
        "icon": "mdi:window-closed-variant",
        "name": "Rear Passenger Window",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.FrontDriverDoor,
        "icon": "mdi:car-door-lock",
        "name": "Front Driver Door Lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.FrontPassengerDoor,
        "icon": "mdi:car-door-lock",
        "name": "Front Passenger Door Lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.RearDriverDoor,
        "icon": "mdi:car-door-lock",
        "name": "Rear Driver Door Lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.RearPassengerDoor,
        "icon": "mdi:car-door-lock",
        "name": "Rear Passenger Door Lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.Trunk,
        "icon": "mdi:car-door-lock",
        "name": "Trunk Door Lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.RUNNING,
        "feature": VehicleFeatures.RemoteStartStatus,
        "icon": "mdi:car-hatchback",
        "name": "Remote Start",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.BATTERY_CHARGING,
        "feature": VehicleFeatures.ChargingStatus,
        "icon": "mdi:ev-station",
        "name": "Charging Status",
        "subscription": True,
        "electric": True,
    },
]

SENSORS = [
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.DistanceToEmpty,
        "name": "Distance To Empty",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.FuelLevel,
        "name": "Fuel Level",
        "unit": PERCENTAGE,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:counter",
        "feature": VehicleFeatures.Odometer,
        "name": "Odometer",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:counter",
        "feature": VehicleFeatures.TripDetailsA,
        "name": "Trip Details A",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:counter",
        "feature": VehicleFeatures.TripDetailsB,
        "name": "Trip Details B",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.FrontDriverTire,
        "name": "Front Driver Tire",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.FrontPassengerTire,
        "name": "Front Passenger Tire",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.RearDriverTire,
        "name": "Rear Driver Tire",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.RearPassengerTire,
        "name": "Rear Passenger Tire",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.SpareTirePressure,
        "name": "Spare Tire Pressure",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        # Maintenance metadata rather than vehicle state, so it belongs in the
        # device page's Diagnostic section, not next to range and door status.
        # No state_class on purpose: this is a threshold that sits flat and then
        # steps at each service, so long-term statistics over it are noise.
        "entity_category": EntityCategory.DIAGNOSTIC,
        "icon": "mdi:wrench-clock",
        "feature": VehicleFeatures.NextService,
        "name": "Next Service",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.ChargeDistance,
        "name": "EV Range",
        "unit": "MI_OR_KM",
        "subscription": True,
        "electric": True,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.ChargeDistanceAC,
        "name": "EV Range AC",
        "unit": "MI_OR_KM",
        "subscription": True,
        "electric": True,
    },
    {
        # device_class BATTERY is what puts the battery indicator in the top
        # right of the device page, the way the official Subaru integration
        # does. It pairs with the Charging Status binary sensor's
        # BATTERY_CHARGING class, which makes the frontend show it charging.
        # icon is None so Home Assistant picks the level-appropriate battery
        # icon instead of a static one.
        "state_class": SensorStateClass.MEASUREMENT,
        "device_class": SensorDeviceClass.BATTERY,
        "icon": None,
        "feature": VehicleFeatures.ChargeLevel,
        "name": "EV Battery Level",
        "unit": PERCENTAGE,
        "subscription": True,
        "electric": True,
    },
    # The API reports these as unix epoch seconds. Marking them TIMESTAMP makes
    # Home Assistant render them as real times ("10 minutes ago") instead of a
    # raw 1786402632.0. A timestamp sensor must not also carry a state_class --
    # measurement statistics are meaningless on a clock reading.
    {
        "device_class": SensorDeviceClass.TIMESTAMP,
        "icon": "mdi:clock-outline",
        "feature": VehicleFeatures.LastTimeStamp,
        "name": "Last Update Timestamp",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": SensorDeviceClass.TIMESTAMP,
        "icon": "mdi:clock-outline",
        "feature": VehicleFeatures.LastTirePressureTimeStamp,
        "name": "Last Tire Pressure Update Timestamp",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.Speed,
        "name": "Speed",
        "unit": "km/h",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:ev-plug-type1",
        "feature": VehicleFeatures.PlugStatus,
        "name": "Plug Status",
        "unit": "",
        "subscription": True,
        "electric": True,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:clock-outline",
        "feature": VehicleFeatures.RemainingChargeTime,
        "name": "Remaining Charge Time",
        "unit": "",
        "subscription": True,
        "electric": True,
    },
    {
        # Always kilometres, unlike evDistance/evDistanceAC which the API
        # converts to the account's preferred unit and tags with evDistanceUnit.
        # This one arrives raw and unlabelled: a Solterra reporting 375.5 here
        # alongside an EV Range of 233.0 mi cannot be miles (no Solterra travels
        # 375 miles), and 375.5 km is 233.3 mi -- the same figure.
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.EvTravelableDistance,
        "name": "EV Travelable Distance",
        "unit": UnitOfLength.KILOMETERS,
        "subscription": True,
        "electric": True,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:ev-plug-type1",
        "feature": VehicleFeatures.ChargeType,
        "name": "Charge Type",
        "unit": "",
        "subscription": True,
        "electric": True,
    },
    {
        # ev_codes decodes this to a string, so no state_class: statistics over
        # a latch state are meaningless, and Home Assistant rejects a numeric
        # state_class on a non-numeric value.
        "state_class": None,
        "icon": "mdi:ev-plug-type1",
        "feature": VehicleFeatures.ConnectorStatus,
        "name": "Connector Status",
        "unit": "",
        "subscription": True,
        "electric": True,
    },
]
