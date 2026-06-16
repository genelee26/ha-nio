"""Device tracker for the NIO vehicle.

Replaces the old shell_command → python_script → POST /api/states chain (the
"ghost entity" that vanished on every HA restart). This is a registry-backed
TrackerEntity: GCJ-02 → WGS-84 conversion happens inline and the position is
present from the first coordinator refresh after startup.
"""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ENTITY_PICTURE
from .coordinator import NioConfigEntry, NioDataUpdateCoordinator
from .entity import NioEntity
from .gcj02 import gcj02_to_wgs84


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NioDeviceTracker(entry.runtime_data.status)])


class NioDeviceTracker(NioEntity, TrackerEntity):
    """Vehicle position in WGS-84."""

    _attr_translation_key = "location"
    _attr_icon = "mdi:car-electric"
    # Bundled logo so the map shows the NIO marker instead of initials.
    _attr_entity_picture = ENTITY_PICTURE

    def __init__(self, coordinator: NioDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "location")

    @property
    def _wgs84(self) -> tuple[float, float] | None:
        pos = self.coordinator.data.get("position_status") or {}
        lat = pos.get("latitude")
        lng = pos.get("longitude")
        if not lat or not lng:
            return None
        return gcj02_to_wgs84(float(lng), float(lat))

    @property
    def latitude(self) -> float | None:
        wgs = self._wgs84
        return wgs[1] if wgs else None

    @property
    def longitude(self) -> float | None:
        wgs = self._wgs84
        return wgs[0] if wgs else None

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def location_accuracy(self) -> float:
        return 10
