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
