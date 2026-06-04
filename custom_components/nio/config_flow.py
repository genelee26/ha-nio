"""Config flow for the NIO integration.

Setup is "paste what you sniffed": the full status request URL from the NIO
iOS app plus the Bearer token. vehicle_id / device_id / sign / timestamp /
app_ver / region are all parsed out of the URL, validated with a live API
call, then stored in the config entry (no more plaintext YAML).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NioApiClient, NioApiError, NioAuthError
from .const import (
    CONF_APP_VER,
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_REGION,
    CONF_SIGN,
    CONF_STATUS_URL,
    CONF_TIMESTAMP,
    CONF_TOKEN,
    CONF_VEHICLE_ID,
    DEFAULT_APP_VER,
    DEFAULT_DAY_END,
    DEFAULT_DAY_START,
    DEFAULT_INTERVAL_DAY,
    DEFAULT_INTERVAL_DRIVING,
    DEFAULT_INTERVAL_NIGHT,
    DEFAULT_MODEL,
    DEFAULT_REGION,
    DOMAIN,
    OPT_DAY_END,
    OPT_DAY_START,
    OPT_INTERVAL_DAY,
    OPT_INTERVAL_DRIVING,
    OPT_INTERVAL_NIGHT,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_STATUS_URL): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): str,
    }
)


def _parse_status_url(url: str) -> dict[str, str]:
    """Extract API parameters from the sniffed status request URL."""
    parsed = urlparse(url.strip())
    # path: /api/2/rvs/vehicle/{vehicle_id}/status
    parts = [p for p in parsed.path.split("/") if p]
    try:
        vehicle_id = parts[parts.index("vehicle") + 1]
    except (ValueError, IndexError) as err:
        raise ValueError("vehicle_id not found in URL path") from err

    qs = parse_qs(parsed.query)

    def q(key: str, default: str | None = None) -> str:
        if key in qs and qs[key]:
            return qs[key][0]
        if default is not None:
            return default
        raise ValueError(f"query parameter '{key}' missing from URL")

    return {
        CONF_VEHICLE_ID: vehicle_id,
        CONF_DEVICE_ID: q("device_id"),
        CONF_SIGN: q("sign"),
        CONF_TIMESTAMP: q("timestamp"),
        CONF_APP_VER: q("app_ver", DEFAULT_APP_VER),
        CONF_REGION: q("region", DEFAULT_REGION),
    }


class NioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config + reauth for a NIO vehicle."""

    VERSION = 1

    async def _validate(self, data: dict[str, Any]) -> str | None:
        """Hit the API once; return an error key or None."""
        client = NioApiClient(
            async_get_clientsession(self.hass),
            token=data[CONF_TOKEN],
            vehicle_id=data[CONF_VEHICLE_ID],
            device_id=data[CONF_DEVICE_ID],
            sign=data[CONF_SIGN],
            timestamp=data[CONF_TIMESTAMP],
            app_ver=data[CONF_APP_VER],
            region=data[CONF_REGION],
        )
        try:
            await client.async_get_status()
        except NioAuthError:
            return "invalid_auth"
        except NioApiError:
            return "cannot_connect"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parsed = _parse_status_url(user_input[CONF_STATUS_URL])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                data = {
                    **parsed,
                    CONF_TOKEN: user_input[CONF_TOKEN].removeprefix("Bearer ").strip(),
                    CONF_MODEL: user_input.get(CONF_MODEL, DEFAULT_MODEL),
                }
                await self.async_set_unique_id(parsed[CONF_VEHICLE_ID])
                self._abort_if_unique_id_configured()
                if (error := await self._validate(data)) is None:
                    return self.async_create_entry(
                        title=f"NIO {data[CONF_MODEL]}", data=data
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Token expired — ask for a fresh one (URL re-paste optional)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data}
            if url := user_input.get(CONF_STATUS_URL):
                try:
                    data.update(_parse_status_url(url))
                except ValueError:
                    errors["base"] = "invalid_url"
            if not errors:
                data[CONF_TOKEN] = (
                    user_input[CONF_TOKEN].removeprefix("Bearer ").strip()
                )
                if (error := await self._validate(data)) is None:
                    return self.async_update_reload_and_abort(entry, data=data)
                errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): str,
                    vol.Optional(CONF_STATUS_URL): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> NioOptionsFlow:
        return NioOptionsFlow()


class NioOptionsFlow(OptionsFlow):
    """Polling cadence options (minutes / hours)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_INTERVAL_DRIVING,
                    default=opts.get(OPT_INTERVAL_DRIVING, DEFAULT_INTERVAL_DRIVING),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Required(
                    OPT_INTERVAL_DAY,
                    default=opts.get(OPT_INTERVAL_DAY, DEFAULT_INTERVAL_DAY),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
                vol.Required(
                    OPT_INTERVAL_NIGHT,
                    default=opts.get(OPT_INTERVAL_NIGHT, DEFAULT_INTERVAL_NIGHT),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=240)),
                vol.Required(
                    OPT_DAY_START,
                    default=opts.get(OPT_DAY_START, DEFAULT_DAY_START),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
                vol.Required(
                    OPT_DAY_END,
                    default=opts.get(OPT_DAY_END, DEFAULT_DAY_END),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
