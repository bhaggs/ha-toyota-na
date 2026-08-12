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
    # Home Assistant composes "<device name> <entity name>" itself. Before this,
    # the device name was concatenated by hand and in the wrong order, which also
    # meant renaming the device did nothing to its entities.
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[list[ToyotaVehicle]],
        key: str,
        name: Union[str, None],
        vin: str,
    ) -> None:
        super().__init__(coordinator)
        # key is identity and must never change; name is only a label and is
        # free to. They used to be the same string, which is why every rename
        # orphaned an entity.
        self._key = key
        self._attr_name = name
        self.vin = vin

    def feature(self, feature: VehicleFeatures):
        """Return the feature dict."""
        if self.vehicle is None:
            return
        return self.vehicle.features.get(feature)

    @property
    def unique_id(self):
        return f"{self.vin}-{self._key}"

    @property
    def device_info(self) -> DeviceInfo:
        model = None
        name = None

        if self.vehicle is not None:
            # Model year included: for a vehicle it is part of how people
            # identify the model, not separate metadata.
            model = f"{self.vehicle.model_year} {self.vehicle.model_name}"
            name = model

        # Set on the coordinator by async_setup_entry; get_brand falls back to
        # Toyota so this stays correct if the attribute is ever missing.
        brand = get_brand(getattr(self.coordinator, "brand", None))

        return {
            "identifiers": {(DOMAIN, self.vin)},
            # Only the default. Renaming the device in the UI now cascades to
            # every entity on it.
            "name": name,
            "model": model,
            "manufacturer": brand.manufacturer,
            "serial_number": self.vin,
        }

    @property
    def vehicle(self) -> Union[ToyotaVehicle, None]:
        """Return the vehicle."""
        return next((v for v in self.coordinator.data if v.vin == self.vin), None)
