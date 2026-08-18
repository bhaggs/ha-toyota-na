from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Union, cast

from toyota_na.vehicle.base_vehicle import ToyotaVehicle, VehicleFeatures
from toyota_na.vehicle.entity_types.ToyotaNumeric import ToyotaNumeric

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

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
                    # Both timestamp classes match on device_class, so the table
                    # says which reading it holds. .get() because the existing
                    # epoch sensors do not carry the key.
                    timestamp_cls = (
                        ToyotaRelativeTimestampSensor
                        if entity_config.get("timestamp_from") == "minutes_remaining"
                        else ToyotaTimestampSensor
                    )
                    sensors.append(
                        timestamp_cls(
                            cast(VehicleFeatures, entity_config["feature"]),
                            cast(str, entity_config["icon"]),
                            coordinator,
                            entity_config["key"],
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
                        entity_config.get("entity_category"),
                        coordinator,
                        entity_config["key"],
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

    def _to_datetime(self, value: float) -> "datetime | None":
        """Interpret the reading as a point in time. Overridden per source."""
        if value >= _EPOCH_MS_THRESHOLD:
            value /= 1000
        # Always UTC: the API gives no zone, and HA localizes for display.
        return datetime.fromtimestamp(value, tz=timezone.utc)

    @property
    def state(self):
        feat = cast(ToyotaNumeric, self.feature(self._vehicle_feature))
        if feat is None or feat.value is None:
            return None
        try:
            value = float(feat.value)
        except (TypeError, ValueError):
            _LOGGER.debug(
                "Non-numeric timestamp %r for %s", feat.value, self._attr_name
            )
            return None
        try:
            moment = self._to_datetime(value)
        except (OSError, OverflowError, ValueError):
            _LOGGER.debug(
                "Out-of-range timestamp %r for %s", feat.value, self._attr_name
            )
            return None
        return moment.isoformat() if moment is not None else None


class ToyotaRelativeTimestampSensor(ToyotaTimestampSensor):
    """A countdown in minutes rendered as the moment it lands on.

    The gateway reports how long a charge has left, not when it will finish.
    Home Assistant renders a TIMESTAMP as relative time, so deriving the moment
    turns "180 min" into "In 3 hours" and lets it count down between polls on
    its own.

    Recomputed each time the coordinator writes state, so the moment shifts
    slightly as the vehicle revises its own estimate. That is the vehicle being
    honest rather than drift on our side.
    """

    def _to_datetime(self, value: float) -> "datetime | None":
        return dt_util.utcnow() + timedelta(minutes=value)


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
        entity_category: Union[EntityCategory, None] = None,
        *args: Any,
    ):
        super().__init__(*args)
        self._icon = icon
        self._state_class = state_class
        self._device_class = device_class
        self._entity_category = entity_category
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
        if not feat:
            return None
        value = feat.value
        # The API reports whole numbers as floats, so a range reads "233.0 mi".
        # Narrowing only when the fraction is zero keeps any real decimal the
        # backend might send, unlike pinning display precision to 0.
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    @property
    def device_class(self):
        return self._device_class

    @property
    def entity_category(self):
        return self._entity_category

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
