from typing import Union

from toyota_na.vehicle.base_vehicle import ToyotaVehicle, VehicleFeatures

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .oneapi import get_brand


class ToyotaNABaseEntity(CoordinatorEntity[list[ToyotaVehicle]]):
    def __init__(
        self,
        coordinator: DataUpdateCoordinator[list[ToyotaVehicle]],
        sensor_name: str,
        vin: str,
    ) -> None:
        super().__init__(coordinator)
        self.sensor_name = sensor_name
        self.vin = vin

    def feature(self, feature: VehicleFeatures):
        """Return the feature dict."""
        if self.vehicle is None:
            return
        return self.vehicle.features.get(feature)

    @property
    def name(self):
        if self.vehicle is not None:
            return f"{self.sensor_name} {self.device_info['name']}"

    @property
    def unique_id(self):
        return f"{self.vin}.{self.sensor_name}"

    @property
    def device_info(self) -> DeviceInfo:
        model = None

        if self.vehicle is not None:
            model = f"{self.vehicle.model_year} {self.vehicle.model_name}"

        # Set on the coordinator by async_setup_entry; get_brand falls back to
        # Toyota so this stays correct if the attribute is ever missing.
        brand = get_brand(getattr(self.coordinator, "brand", None))

        return {
            "identifiers": {(DOMAIN, self.vin)},
            "name": model,
            "model": model,
            "manufacturer": brand.manufacturer,
        }

    @property
    def vehicle(self) -> Union[ToyotaVehicle, None]:
        """Return the vehicle."""
        return next((v for v in self.coordinator.data if v.vin == self.vin), None)
