"""Config-entry diagnostics — downloadable from the integration page.

A redacted bundle to send to the developer when something looks off (especially
with debug mode on): the last raw server responses (status + orders gateway),
the normalized order ledger, and config/options with credentials masked. The
debug-mode refresh buttons make sure these last responses are fresh first.

The captured status ``query`` is masked **param-by-param** (not wholesale): the
secret/identifying params (sign, device_id, timestamp) are hidden, but the
field list and app_ver stay visible — a narrow ``field=`` set is the usual
cause of sensors stuck at "unknown", and we want that clue to survive in a
shared bundle. ``capture_fields`` spells the same thing out explicitly.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .capture import missing_critical_fields, query_fields
from .const import CONF_QUERY, CONF_TOKEN, CONF_VEHICLE_ID, OPT_DEBUG
from .coordinator import NioConfigEntry, NioRuntimeData

REDACTED = "**REDACTED**"

# Credentials, per-vehicle identifiers and GPS are stripped from everything
# echoed back, so the bundle is safe to share. NOTE: CONF_QUERY is deliberately
# absent — it's masked param-by-param (see ``_redact_query``) instead of
# wholesale, to keep the diagnostically useful field=/app_ver visible.
TO_REDACT = {
    CONF_TOKEN,
    CONF_VEHICLE_ID,
    "device_id",
    "sign",
    "timestamp",
    "vinCode",
    "vehicleId",
    "longitude",
    "latitude",
}

# Params hidden inside the status query string; everything else (field, app_ver,
# region, app_id, lang) is kept.
_QUERY_SECRET_PARAMS = {"sign", "device_id", "timestamp"}


def _redact_query(query: str) -> str:
    """Mask only the secret params in a status query; keep field=/app_ver/etc."""
    out = []
    for part in query.split("&"):
        key, sep, _ = part.partition("=")
        out.append(f"{key}={REDACTED}" if sep and key in _QUERY_SECRET_PARAMS else part)
    return "&".join(out)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NioConfigEntry
) -> dict[str, Any]:
    """Return a redacted diagnostics bundle for the entry."""
    entry_data = async_redact_data(dict(entry.data), TO_REDACT)
    raw_query = entry.data.get(CONF_QUERY) or ""
    if isinstance(entry_data.get(CONF_QUERY), str):
        entry_data[CONF_QUERY] = _redact_query(entry_data[CONF_QUERY])

    diag: dict[str, Any] = {
        "entry": {
            "version": entry.version,
            "data": entry_data,
            "options": dict(entry.options),
        },
        "debug_enabled": bool(entry.options.get(OPT_DEBUG, False)),
        # Which status sections the capture requests. A missing critical section
        # can never populate (the sign-locked query can't be widened) → those
        # sensors stay "unknown" until the user re-captures a fuller request.
        "capture_fields": {
            "requested": sorted(query_fields(raw_query)),
            "missing_critical": missing_critical_fields(raw_query),
        },
    }

    runtime = entry.runtime_data
    if isinstance(runtime, NioRuntimeData):
        # Best-effort: refresh both raw responses on download, so the bundle
        # always carries them even if no refresh button was pressed first
        # (the orders client doesn't fetch on setup). A failed fetch is fine —
        # the client still keeps whatever payload (incl. an error) it last saw.
        for fetch in (
            runtime.status.client.async_get_status,
            runtime.orders.client.async_fetch_recent,
        ):
            try:
                await fetch()
            except Exception:  # noqa: BLE001 - diagnostics must never fail
                pass
        diag["status_last_response"] = async_redact_data(
            runtime.status.client.last_response or {}, TO_REDACT
        )
        diag["orders"] = async_redact_data(runtime.orders.diagnostics(), TO_REDACT)

    return diag
