"""The NIO integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import NioApiClient
from .const import (
    CONF_APP_VER,
    CONF_DEVICE_ID,
    CONF_REGION,
    CONF_SIGN,
    CONF_TIMESTAMP,
    CONF_TOKEN,
    CONF_VEHICLE_ID,
    DEFAULT_APP_VER,
    DEFAULT_REGION,
    DOMAIN,
    STATIC_URL_BASE,
)
from .coordinator import NioConfigEntry, NioDataUpdateCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: NioConfigEntry) -> bool:
    """Set up NIO from a config entry."""
    # Serve bundled assets (map marker logo, car renders, lovelace card)
    # and auto-register the card JS — once per HA run.
    if not hass.data.setdefault(DOMAIN, {}).get("static_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATIC_URL_BASE,
                    str(Path(__file__).parent / "static"),
                    cache_headers=True,
                )
            ]
        )
        integration = await async_get_integration(hass, DOMAIN)
        add_extra_js_url(
            hass, f"{STATIC_URL_BASE}/nio-car-card.js?v={integration.version}"
        )
        hass.data[DOMAIN]["static_registered"] = True
    client = NioApiClient(
        async_get_clientsession(hass),
        token=entry.data[CONF_TOKEN],
        vehicle_id=entry.data[CONF_VEHICLE_ID],
        device_id=entry.data[CONF_DEVICE_ID],
        sign=entry.data[CONF_SIGN],
        timestamp=entry.data[CONF_TIMESTAMP],
        app_ver=entry.data.get(CONF_APP_VER, DEFAULT_APP_VER),
        region=entry.data.get(CONF_REGION, DEFAULT_REGION),
    )
    coordinator = NioDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: NioConfigEntry) -> None:
    """Reload on options change so new intervals apply."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NioConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
