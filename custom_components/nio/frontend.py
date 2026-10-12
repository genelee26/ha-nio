"""Serve the bundled Lovelace card and register it as a dashboard resource.

``add_extra_js_url`` alone is racy: the URL is baked into ``index.html`` at
render time, but HA serves the frontend before custom integrations finish
setting up. A tab that stayed open across a restart (or was opened during
startup) never loads the card and shows "Configuration error" until F5.
Lovelace resources are persisted in storage and fetched by the dashboard
itself, so they don't have that problem — same mechanism HACS cards use.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN, STATIC_URL_BASE

_LOGGER = logging.getLogger(__name__)

CARD_PATH = f"{STATIC_URL_BASE}/nio-car-card.js"


def _resources(hass: HomeAssistant):
    """Return the storage-mode resource collection, or None (YAML mode)."""
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    # YAML-mode collections are read-only; only storage mode has create/update.
    if resources is None or not hasattr(resources, "async_create_item"):
        return None
    return resources


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve static assets and register the card JS — once per HA run."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("static_registered"):
        return

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
    url = f"{CARD_PATH}?v={integration.version}"

    # Kept as fallback for YAML-mode dashboards. Same URL as the resource, so
    # the browser's module map imports it only once.
    add_extra_js_url(hass, url)
    domain_data["static_registered"] = True

    resources = _resources(hass)
    if resources is None:
        return
    try:
        await resources.async_get_info()  # loads the collection if needed
        for item in resources.async_items():
            if item["url"].split("?")[0] == CARD_PATH:
                if item["url"] != url:
                    await resources.async_update_item(
                        item["id"], {"res_type": "module", "url": url}
                    )
                return
        await resources.async_create_item({"res_type": "module", "url": url})
    except Exception:  # noqa: BLE001 — never block setup over a resource
        _LOGGER.warning("Could not register %s as a Lovelace resource", url, exc_info=True)


async def async_unregister_card(hass: HomeAssistant) -> None:
    """Drop the resource when the last entry is removed (avoids a dead 404 module)."""
    resources = _resources(hass)
    if resources is None:
        return
    try:
        await resources.async_get_info()
        for item in list(resources.async_items()):
            if item["url"].split("?")[0] == CARD_PATH:
                await resources.async_delete_item(item["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Could not remove the NIO card Lovelace resource", exc_info=True)
