"""Base entity for the NIO integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MODEL, CONF_VEHICLE_ID, DEFAULT_MODEL, DOMAIN
from .coordinator import NioDataUpdateCoordinator


class NioEntity(CoordinatorEntity[NioDataUpdateCoordinator]):
    """Couples an entity to the vehicle device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NioDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        vehicle_id = entry.data[CONF_VEHICLE_ID]
        model = entry.data.get(CONF_MODEL, DEFAULT_MODEL)
        self._attr_unique_id = f"{vehicle_id}_{key}"
        fota = (coordinator.data or {}).get("fota_status") or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, vehicle_id)},
            manufacturer="NIO",
            model=model,
            name=f"NIO {model}",
            sw_version=fota.get("current_version"),
        )


class NioOrdersEntity(CoordinatorEntity):
    """Base for service-order entities, linked to the same vehicle device.

    Unlike :class:`NioEntity` it sets *no* device fields (name/model/sw_version)
    — those belong to the status entities; this only carries the identifiers so
    the orders entities group under the existing NIO device. Its coordinator's
    data is the flat order snapshot, not the vehicle status payload.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator)
        vehicle_id = coordinator.config_entry.data[CONF_VEHICLE_ID]
        self._attr_unique_id = f"{vehicle_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, vehicle_id)})
