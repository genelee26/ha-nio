"""Refresh button — replaces script.refresh_nio_data."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import OPT_DEBUG
from .coordinator import NioConfigEntry, NioDataUpdateCoordinator
from .entity import NioEntity, NioOrdersEntity


@callback
def _debug_diagnostics_notice(coordinator) -> None:
    """In debug mode, point the user at the diagnostics download after a refresh."""
    entry = coordinator.config_entry
    if not entry.options.get(OPT_DEBUG):
        return
    async_create_notification(
        coordinator.hass,
        "已刷新并捕获服务器完整返回。请到 设置 → 设备与服务 → NIO → 右上角 ⋮ → "
        "「下载诊断」，把文件发给开发者帮助定位问题。",
        title="NIO 调试：诊断已就绪",
        notification_id="nio_debug_diagnostics",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        [
            NioRefreshButton(runtime.status),
            NioOrdersRefreshButton(runtime.orders),
        ]
    )


class NioRefreshButton(NioEntity, ButtonEntity):
    """Trigger an immediate poll of the NIO API."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: NioDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
        _debug_diagnostics_notice(self.coordinator)


class NioOrdersRefreshButton(NioOrdersEntity, ButtonEntity):
    """Trigger an immediate refresh of the service-order ledger."""

    _attr_translation_key = "refresh_orders"
    _attr_icon = "mdi:receipt-text-clock-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refresh_orders")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
        _debug_diagnostics_notice(self.coordinator)
