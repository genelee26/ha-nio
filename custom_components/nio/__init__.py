"""The NIO integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import NioApiClient, NioOrdersClient
from .capture import missing_critical_fields, reconstruct_query_v1
from .const import (
    CONF_MODEL,
    CONF_QUERY,
    CONF_TOKEN,
    CONF_VEHICLE_ID,
    DEFAULT_MODEL,
    DOMAIN,
    STATIC_URL_BASE,
)
from .coordinator import NioConfigEntry, NioDataUpdateCoordinator, NioRuntimeData
from .orders_coordinator import NioOrdersCoordinator
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]


def _check_capture_completeness(hass: HomeAssistant, entry: NioConfigEntry) -> None:
    """Raise/clear a repair issue if the capture omits critical field sections.

    A narrow ``field=`` set is the usual cause of sensors stuck at "unknown":
    the server only returns the sections the (sign-locked) query requested, so
    the missing ones can never populate. Re-evaluated on every setup, so the
    issue clears itself once a fuller capture is pasted.
    """
    issue_id = f"incomplete_capture_{entry.entry_id}"
    missing = missing_critical_fields(entry.data.get(CONF_QUERY, ""))
    if missing:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="incomplete_capture",
            translation_placeholders={"fields": ", ".join(missing)},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


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
    async_register_services(hass)  # idempotent (self-guards on has_service)
    session = async_get_clientsession(hass)
    client = NioApiClient(
        session,
        token=entry.data[CONF_TOKEN],
        vehicle_id=entry.data[CONF_VEHICLE_ID],
        query=entry.data[CONF_QUERY],
    )
    coordinator = NioDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    orders_coordinator = NioOrdersCoordinator(
        hass, entry, NioOrdersClient(session, token=entry.data[CONF_TOKEN])
    )
    try:
        await orders_coordinator.async_setup()
    except Exception:  # noqa: BLE001 - orders are non-critical; never block setup
        _LOGGER.exception("NIO orders setup failed; continuing without orders")

    entry.runtime_data = NioRuntimeData(status=coordinator, orders=orders_coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _check_capture_completeness(hass, entry)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: NioConfigEntry) -> bool:
    """Migrate v1 (per-field) entries to v2 (verbatim query).

    v1 stored device_id/sign/timestamp/app_ver/region separately and the client
    rebuilt the query from them. v2 stores the query string itself. We rebuild
    the *exact* string the v1 client used to send, so an existing, still-valid
    sign keeps validating — the upgrade is seamless and requires no re-sniff.
    """
    if entry.version == 1:
        old = entry.data
        new = {
            CONF_TOKEN: old[CONF_TOKEN],
            CONF_VEHICLE_ID: old[CONF_VEHICLE_ID],
            CONF_QUERY: reconstruct_query_v1(old),
            CONF_MODEL: old.get(CONF_MODEL, DEFAULT_MODEL),
        }
        hass.config_entries.async_update_entry(entry, data=new, version=2)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: NioConfigEntry) -> None:
    """Reload on options change so new intervals apply."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NioConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
