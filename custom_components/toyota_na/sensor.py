from datetime import datetime, timezone
import logging
from typing import Any, Union, cast

from toyota_na.vehicle.base_vehicle import ToyotaVehicle, VehicleFeatures
from toyota_na.vehicle.entity_types.ToyotaNumeric import ToyotaNumeric

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .base_entity import ToyotaNABaseEntity
from .const import DOMAIN, SENSORS

_LOGGER = logging.getLogger(__name__)

# Epoch values above this are milliseconds, not seconds: as seconds it would be
# the year 5138. The API is undocumented and has been inconsistent about units.
_EPOCH_MS_THRESHOLD = 1e11


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Set up the sensor platform."""
    sensors = []

    coordinator: DataUpdateCoordinator[list[ToyotaVehicle]] = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]

    for vehicle in coordinator.data:
        for feature_sensor in SENSORS:
            feature = vehicle.features.get(
                cast(VehicleFeatures, feature_sensor["feature"])
            )

            entity_config = feature_sensor
            if entity_config and isinstance(feature, ToyotaNumeric):
                if vehicle.electric is False and cast(bool, entity_config["electric"]):
                    continue
                if vehicle.subscribed is False and cast(bool, entity_config["subscription"]):
                    continue

                # .get() rather than [] because not every sensor carries every
                # key: timestamps have a device_class and no unit or state_class.
                # Indexing here is what broke the previous attempt at this - one
                # missing key raised KeyError and took down the whole platform.
                if entity_config.get("device_class") == SensorDeviceClass.TIMESTAMP:
                    sensors.append(
                        ToyotaTimestampSensor(
                            cast(VehicleFeatures, entity_config["feature"]),
                            cast(str, entity_config["icon"]),
                            coordinator,
                            entity_config["name"],
                            vehicle.vin,
                        )
                    )
                    continue

                sensors.append(
                    ToyotaNumericSensor(
                        cast(VehicleFeatures, feature_sensor["feature"]),
                        cast(str, entity_config["icon"]),
                        cast(str, entity_config.get("unit", "")),
                        cast(SensorStateClass, entity_config.get("state_class")),
                        cast(SensorDeviceClass, entity_config.get("device_class")),
                        coordinator,
                        entity_config["name"],
                        vehicle.vin,
                    )
                )

    async_add_devices(sensors, True)


class ToyotaTimestampSensor(ToyotaNABaseEntity):
    """A unix epoch reading rendered as an actual point in time.

    Reports an ISO 8601 string rather than a datetime object. These entities
    derive from CoordinatorEntity, not SensorEntity, so nothing converts a
    datetime for us -- str() on one yields a space separator that Home
    Assistant will not accept for a timestamp device class.
    """

    def __init__(self, vehicle_feature: VehicleFeatures, icon: str, *args: Any):
        super().__init__(*args)
        self._icon = icon
        self._vehicle_feature = vehicle_feature

    @property
    def icon(self) -> str:
        return self._icon

    @property
    def device_class(self):
        return SensorDeviceClass.TIMESTAMP

    @property
    def state(self):
        feat = cast(ToyotaNumeric, self.feature(self._vehicle_feature))
        if feat is None or feat.value is None:
            return None
        try:
            value = float(feat.value)
        except (TypeError, ValueError):
            _LOGGER.debug(
                "Non-numeric timestamp %r for %s", feat.value, self.sensor_name
            )
            return None
        if value >= _EPOCH_MS_THRESHOLD:
            value /= 1000
        try:
            # Always UTC: the API gives no zone, and HA localizes for display.
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            _LOGGER.debug(
                "Out-of-range timestamp %r for %s", feat.value, self.sensor_name
            )
            return None


class ToyotaNumericSensor(ToyotaNABaseEntity):
    _icon: str
    _vehicle_feature: VehicleFeatures

    def __init__(
        self,
        vehicle_feature: VehicleFeatures,
        icon: str,
        unit_of_measurement: str,
        state_class: Union[SensorStateClass, str],
        device_class: Union[SensorDeviceClass, str, None] = None,
        *args: Any,
    ):
        super().__init__(*args)
        self._icon = icon
        self._state_class = state_class
        self._device_class = device_class
        self._unit_of_measurement = unit_of_measurement
        self._vehicle_feature = vehicle_feature

    @property
    def icon(self) -> str:
        # None lets Home Assistant use the device class icon, which for a
        # battery tracks the charge level instead of sitting static.
        return self._icon

    @property
    def state(self):
        feat = cast(ToyotaNumeric, self.feature(self._vehicle_feature))
        if feat:
            return feat.value

    @property
    def device_class(self):
        return self._device_class

    @property
    def state_class(self):
        return self._state_class

    @property
    def unit_of_measurement(self):

        # We need to poll the unit of measure from the service itself to ensure we're passing
        # the correct unit of measure to the sensor.
        if self._unit_of_measurement == "MI_OR_KM":
            feature = cast(ToyotaNumeric, self.feature(self._vehicle_feature))
            if hasattr(feature,'unit'):
                _unit = feature.unit
                if _unit == "mi":
                    return UnitOfLength.MILES
                elif _unit == "km":
                    return UnitOfLength.KILOMETERS

        return self._unit_of_measurement
