"""Refresh button — replaces script.refresh_nio_data."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NioConfigEntry, NioDataUpdateCoordinator
from .entity import NioEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NioRefreshButton(entry.runtime_data)])


class NioRefreshButton(NioEntity, ButtonEntity):
    """Trigger an immediate poll of the NIO API."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: NioDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
