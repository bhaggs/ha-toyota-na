import asyncio
from typing import Any

from toyota_na.vehicle.base_vehicle import (
    ApiVehicleGeneration,
    ToyotaVehicle,
    VehicleFeatures,
)
from toyota_na.vehicle.entity_types.ToyotaLockableOpening import ToyotaLockableOpening
from toyota_na.vehicle.entity_types.ToyotaOpening import ToyotaOpening
from toyota_na.vehicle.entity_types.ToyotaRemoteStart import ToyotaRemoteStart


from homeassistant.components.lock import (
    LockEntity,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .base_entity import ToyotaNABaseEntity
from .const import (
    COMMAND_MAP,
    DOMAIN,
    DOOR_LOCK,
    DOOR_UNLOCK,
    REFRESH_SETTLE_SECONDS,
    TRUNK_LOCK,
    TRUNK_UNLOCK,
)


def _has_trunk_lock(vehicle: ToyotaVehicle) -> bool:
    """Whether the vehicle takes trunk-lock and trunk-unlock.

    Only where its vehicle listing says so: the commands are confirmed on a
    Solterra, and a vehicle that does not advertise them would refuse them.
    The legacy 17CY protocol has no equivalent at all.
    """
    if vehicle.generation == ApiVehicleGeneration.CY17:
        return False
    capabilities = getattr(vehicle, "capabilities", None) or {}
    return capabilities.get("trunkLockUnlockCapable") is True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Set up the binary_sensor platform."""
    locks = []

    coordinator: DataUpdateCoordinator[list[ToyotaVehicle]] = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]

    for vehicle in coordinator.data:
        if vehicle.subscribed is False:
            continue
        doors = ToyotaLock(
            coordinator,
            "door_lock",
            "Doors",
            vehicle.vin,
        )
        locks.append(doors)
        if _has_trunk_lock(vehicle):
            # The hatch has its own lock now, so the doors stop counting it: an
            # unlocked hatch would otherwise show the doors as unlocked too.
            doors.exclude_trunk = True
            locks.append(
                ToyotaTrunkLock(
                    coordinator,
                    # The gateway calls it the trunk; every vehicle this fork
                    # supports has a hatch, so that is what it is named.
                    "trunk_lock",
                    "Hatch",
                    vehicle.vin,
                )
            )

    async_add_devices(locks, True)


class ToyotaLock(ToyotaNABaseEntity, LockEntity):

    _state_changing = False
    exclude_trunk = False

    def __init__(
        self,
        vin,
        *args: Any,
    ):
        super().__init__(vin, *args)

    @property
    def icon(self):
        return "mdi:car-key"

    @property
    def is_locked(self):
        if self.vehicle is None:
            return None

        all_locks = [
            feature
            for key, feature in self.vehicle.features.items()
            if isinstance(feature, ToyotaLockableOpening)
            and not (self.exclude_trunk and key == VehicleFeatures.Trunk)
        ]

        if not all_locks:
            return None

        return all(lock.locked for lock in all_locks)

    @property
    def is_locking(self):
        return self._state_changing is True and self.is_locked is False

    @property
    def is_unlocking(self):
        return self._state_changing is True and self.is_locked is True

    async def async_lock(self, **kwargs):
        """Lock all or specified locks. A code to lock the lock with may optionally be specified."""
        await self.toggle_lock(DOOR_LOCK)

    async def async_unlock(self, **kwargs):
        """Unlock all or specified locks. A code to unlock the lock with may optionally be specified."""
        await self.toggle_lock(DOOR_UNLOCK)

    async def toggle_lock(self, command: str):
        """Set the lock state via the provided command string."""
        if self.vehicle is not None:
            # Captured now: the entity drops it five seconds after the call
            # began, long before the vehicle's confirmation comes back.
            context = self._context
            self._state_changing = True
            self.async_write_ha_state()
            await self.vehicle.send_command(COMMAND_MAP[command])
            self.hass.async_create_task(self._background_refresh(context))

    async def _background_refresh(self, context=None):
        """Poll for updated vehicle state after a command, then refresh the coordinator."""
        try:
            await self.vehicle.poll_vehicle_refresh()
            await asyncio.sleep(REFRESH_SETTLE_SECONDS)
            self._state_changing = False
            # Credit the confirmed state to whoever locked or unlocked.
            self.coordinator.async_set_cause([self.vin], context)
            await self.coordinator.async_request_refresh()
        except Exception:
            self._state_changing = False
            self.async_write_ha_state()

    @property
    def available(self):
        return self.vehicle is not None


class ToyotaTrunkLock(ToyotaLock):
    """The hatch, locked and unlocked on its own.

    Its state is the lock the vehicle reports for the trunk, the same reading
    the Hatch lock binary sensor shows. After a command it refreshes the same
    way the door lock does, so the state follows without pressing Refresh.
    """

    @property
    def icon(self):
        return "mdi:car-back"

    @property
    def is_locked(self):
        if self.vehicle is None:
            return None
        trunk = self.vehicle.features.get(VehicleFeatures.Trunk)
        if not isinstance(trunk, ToyotaLockableOpening):
            return None
        return trunk.locked

    async def async_lock(self, **kwargs):
        await self.toggle_lock(TRUNK_LOCK)

    async def async_unlock(self, **kwargs):
        await self.toggle_lock(TRUNK_UNLOCK)
