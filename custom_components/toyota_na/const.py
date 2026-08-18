from toyota_na.vehicle.base_vehicle import VehicleFeatures

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfPressure,
    UnitOfTime,
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
        "action": HAZARDS_ON,
        "icon": "mdi:hazard-lights",
        "key": "hazards",
        "name": "Hazards",
    },
    {
        "action": BUZZER,
        "icon": "mdi:bullhorn",
        "key": "buzzer",
        "name": "Buzzer",
    },
    {
        "action": REFRESH,
        "icon": "mdi:refresh",
        # Unlike the others this wakes the telematics unit to upload fresh
        # state, so it draws on the 12V battery.
        "key": "refresh",
        "name": "Refresh",
    },
]

BINARY_SENSORS = [
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.FrontDriverDoor,
        "icon": "mdi:car-door",
        "key": "front_driver_door",
        "name": "Front driver door",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.FrontPassengerDoor,
        "icon": "mdi:car-door",
        "key": "front_passenger_door",
        "name": "Front passenger door",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.RearDriverDoor,
        "icon": "mdi:car-door",
        "key": "rear_driver_door",
        "name": "Rear driver door",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.RearPassengerDoor,
        "icon": "mdi:car-door",
        "key": "rear_passenger_door",
        "name": "Rear passenger door",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.Hood,
        "icon": "mdi:car-door",
        "key": "hood",
        "name": "Hood",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.DOOR,
        "feature": VehicleFeatures.Trunk,
        "icon": "mdi:car-door",
        "key": "trunk",
        "name": "Trunk",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.Moonroof,
        "icon": "mdi:window-closed-variant",
        "key": "moonroof",
        "name": "Moonroof",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.FrontDriverWindow,
        "icon": "mdi:window-closed-variant",
        "key": "front_driver_window",
        "name": "Front driver window",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.FrontPassengerWindow,
        "icon": "mdi:window-closed-variant",
        "key": "front_passenger_window",
        "name": "Front passenger window",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.RearDriverWindow,
        "icon": "mdi:window-closed-variant",
        "key": "rear_driver_window",
        "name": "Rear driver window",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.WINDOW,
        "feature": VehicleFeatures.RearPassengerWindow,
        "icon": "mdi:window-closed-variant",
        "key": "rear_passenger_window",
        "name": "Rear passenger window",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.FrontDriverDoor,
        "icon": "mdi:car-door-lock",
        "key": "front_driver_door_lock",
        "name": "Front driver door lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.FrontPassengerDoor,
        "icon": "mdi:car-door-lock",
        "key": "front_passenger_door_lock",
        "name": "Front passenger door lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.RearDriverDoor,
        "icon": "mdi:car-door-lock",
        "key": "rear_driver_door_lock",
        "name": "Rear driver door lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.RearPassengerDoor,
        "icon": "mdi:car-door-lock",
        "key": "rear_passenger_door_lock",
        "name": "Rear passenger door lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.LOCK,
        "feature": VehicleFeatures.Trunk,
        "icon": "mdi:car-door-lock",
        "key": "trunk_lock",
        "name": "Trunk lock",
        "subscription": True,
        "electric": False,
    },
    {
        "device_class": BinarySensorDeviceClass.BATTERY_CHARGING,
        "feature": VehicleFeatures.ChargingStatus,
        "icon": "mdi:car-electric",
        "key": "charging",
        "name": "Charging",
        "subscription": True,
        "electric": True,
    },
]

SENSORS = [
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.DistanceToEmpty,
        "key": "distance_to_empty",
        "name": "Distance to empty",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.FuelLevel,
        "key": "fuel_level",
        "name": "Fuel level",
        "unit": PERCENTAGE,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:counter",
        "feature": VehicleFeatures.Odometer,
        "key": "odometer",
        "name": "Odometer",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:counter",
        "feature": VehicleFeatures.TripDetailsA,
        "key": "trip_a",
        "name": "Trip A",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:counter",
        "feature": VehicleFeatures.TripDetailsB,
        "key": "trip_b",
        "name": "Trip B",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.FrontDriverTire,
        "key": "front_driver_tire_pressure",
        "name": "Front driver tire pressure",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.FrontPassengerTire,
        "key": "front_passenger_tire_pressure",
        "name": "Front passenger tire pressure",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.RearDriverTire,
        "key": "rear_driver_tire_pressure",
        "name": "Rear driver tire pressure",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.RearPassengerTire,
        "key": "rear_passenger_tire_pressure",
        "name": "Rear passenger tire pressure",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:car-tire-alert",
        "feature": VehicleFeatures.SpareTirePressure,
        "key": "spare_tire_pressure",
        "name": "Spare tire pressure",
        "unit": UnitOfPressure.PSI,
        "subscription": False,
        "electric": False,
    },
    {
        "entity_category": EntityCategory.DIAGNOSTIC,
        "icon": "mdi:wrench-clock",
        "feature": VehicleFeatures.NextService,
        "key": "next_service",
        "name": "Next service",
        "unit": "MI_OR_KM",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.ChargeDistance,
        "key": "ev_range",
        "name": "EV range",
        "unit": "MI_OR_KM",
        "subscription": True,
        "electric": True,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.ChargeDistanceAC,
        "key": "ev_range_ac",
        "name": "EV range with A/C",
        "unit": "MI_OR_KM",
        "subscription": True,
        "electric": True,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "device_class": SensorDeviceClass.BATTERY,
        "icon": None,
        "feature": VehicleFeatures.ChargeLevel,
        "key": "ev_battery",
        "name": "EV battery",
        "unit": PERCENTAGE,
        "subscription": True,
        "electric": True,
    },
    {
        "device_class": SensorDeviceClass.TIMESTAMP,
        "icon": "mdi:clock-outline",
        "feature": VehicleFeatures.LastTimeStamp,
        "key": "last_updated",
        "name": "Last updated",
        "subscription": False,
        "electric": False,
    },
    {
        "device_class": SensorDeviceClass.TIMESTAMP,
        "icon": "mdi:clock-outline",
        "feature": VehicleFeatures.LastTirePressureTimeStamp,
        "key": "tire_pressure_last_updated",
        "name": "Tire pressure last updated",
        "subscription": False,
        "electric": False,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.Speed,
        "key": "speed",
        "name": "Speed",
        "unit": "km/h",
        "subscription": False,
        "electric": False,
    },
    {
        # Decoded to a string by ev_codes, so no state_class.
        "state_class": None,
        "icon": "mdi:ev-plug-tesla",
        "feature": VehicleFeatures.PlugStatus,
        "key": "charging_plug",
        "name": "Charging plug",
        "unit": "",
        "subscription": True,
        "electric": True,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "device_class": SensorDeviceClass.DURATION,
        "icon": "mdi:battery-clock",
        "feature": VehicleFeatures.RemainingChargeTime,
        "key": "charging_time_remaining",
        "name": "Charging time remaining",
        "unit": UnitOfTime.MINUTES,
        "subscription": True,
        "electric": True,
    },
    {
        # The same reading as charging_time_remaining, expressed as the moment
        # it lands on. HA renders a TIMESTAMP as relative time, so this shows as
        # "In 3 hours" rather than "180 min". No state_class or unit: a
        # timestamp takes neither.
        "device_class": SensorDeviceClass.TIMESTAMP,
        "timestamp_from": "minutes_remaining",
        "icon": "mdi:battery-clock-outline",
        "feature": VehicleFeatures.RemainingChargeTime,
        "key": "charging_finishes",
        "name": "Charging finishes",
        "subscription": True,
        "electric": True,
    },
    {
        # Always kilometres, unlike evDistance/evDistanceAC which the API
        # converts to the account's preferred unit and tags with evDistanceUnit.
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "feature": VehicleFeatures.EvTravelableDistance,
        "key": "ev_travelable_distance",
        "name": "EV travelable distance",
        "unit": UnitOfLength.KILOMETERS,
        "subscription": True,
        "electric": True,
    },
    {
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:ev-plug-tesla",
        "feature": VehicleFeatures.ChargeType,
        "key": "charging_type",
        "name": "Charging type",
        "unit": "",
        "subscription": True,
        "electric": True,
    },
    {
        "state_class": None,
        "icon": "mdi:ev-plug-tesla",
        "feature": VehicleFeatures.ConnectorStatus,
        "key": "charging_connector",
        "name": "Charging connector",
        "unit": "",
        "subscription": True,
        "electric": True,
    },
]
