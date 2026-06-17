"""Integration services.

``nio.get_service_orders`` is a response-only service: it returns the vehicle's
full service-order (billing) history on demand, so the data never has to live in
the state machine / recorder. The custom card calls it when its billing popup
opens and does all month/order navigation client-side.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN
from .coordinator import NioRuntimeData

SERVICE_GET_ORDERS = "get_service_orders"

GET_ORDERS_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Optional("include_cancelled", default=True): cv.boolean,
    }
)


def _runtime_for_device(hass: HomeAssistant, device_id: str | None) -> NioRuntimeData:
    """Resolve the orders runtime for a device_id (or the sole vehicle)."""
    candidates = []
    if device_id:
        device = dr.async_get(hass).async_get(device_id)
        if device is not None:
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is not None and entry.domain == DOMAIN:
                    candidates.append(entry)
    else:
        candidates = list(hass.config_entries.async_entries(DOMAIN))

    runtimes = [
        e.runtime_data
        for e in candidates
        if isinstance(getattr(e, "runtime_data", None), NioRuntimeData)
    ]
    if not runtimes:
        raise ServiceValidationError(
            "No set-up NIO vehicle found for that device_id"
        )
    if len(runtimes) > 1:
        raise ServiceValidationError(
            "Multiple NIO vehicles configured — pass device_id to choose one"
        )
    return runtimes[0]


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once (idempotent across config entries)."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_ORDERS):
        return

    async def _get_service_orders(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime_for_device(hass, call.data.get("device_id"))
        return runtime.orders.orders_response(
            include_cancelled=call.data["include_cancelled"]
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ORDERS,
        _get_service_orders,
        schema=GET_ORDERS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
