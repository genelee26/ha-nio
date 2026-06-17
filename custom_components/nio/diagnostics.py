"""Config-entry diagnostics — downloadable from the integration page.

A redacted bundle to send to the developer when something looks off (especially
with debug mode on): the last raw server responses (status + orders gateway),
the normalized order ledger, and config/options with credentials masked. The
debug-mode refresh buttons make sure these last responses are fresh first.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_QUERY, CONF_TOKEN, CONF_VEHICLE_ID, OPT_DEBUG
from .coordinator import NioConfigEntry, NioRuntimeData

# Credentials, per-vehicle identifiers and GPS are stripped from everything
# echoed back, so the bundle is safe to share.
TO_REDACT = {
    CONF_TOKEN,
    CONF_QUERY,
    CONF_VEHICLE_ID,
    "device_id",
    "sign",
    "timestamp",
    "vinCode",
    "vehicleId",
    "longitude",
    "latitude",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NioConfigEntry
) -> dict[str, Any]:
    """Return a redacted diagnostics bundle for the entry."""
    diag: dict[str, Any] = {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "debug_enabled": bool(entry.options.get(OPT_DEBUG, False)),
    }

    runtime = entry.runtime_data
    if isinstance(runtime, NioRuntimeData):
        diag["status_last_response"] = async_redact_data(
            runtime.status.client.last_response or {}, TO_REDACT
        )
        diag["orders"] = async_redact_data(runtime.orders.diagnostics(), TO_REDACT)

    return diag
