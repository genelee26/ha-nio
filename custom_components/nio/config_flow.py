"""Config flow for the NIO integration.

Setup is "enter what you sniffed": the four request values from the NIO iOS
app's vehicle-status call — vehicle_id (URL path), device_id, sign and
timestamp (query string) — plus the Authorization Bearer token (request
header). sign and timestamp are kept together because the signature is computed
over the timestamp; they are replayed unchanged. app_ver / region use the
bundled defaults. Everything is stored in the config entry (no plaintext YAML).

Options is a menu: polling cadence (number-entry boxes) and credentials
(update the token / any of the sniffed ids without waiting for a reauth prompt).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import NioApiClient, NioApiError, NioAuthError
from .const import (
    CONF_APP_VER,
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_REGION,
    CONF_SIGN,
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

# The five values sniffed from one app status request. sign+timestamp are a
# pair (the signature is computed over the timestamp), so both are required.
STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VEHICLE_ID): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_SIGN): str,
        vol.Required(CONF_TIMESTAMP): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): str,
    }
)

# Fields that identify the request; entered on setup, re-enterable on reauth.
ID_FIELDS = (CONF_VEHICLE_ID, CONF_DEVICE_ID, CONF_SIGN, CONF_TIMESTAMP)


def _clean(value: str) -> str:
    """Trim and drop a stray ``Bearer `` prefix users paste with the token."""
    return value.removeprefix("Bearer ").strip()


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> str | None:
    """Hit the API once with the given credentials; return an error key or None."""
    client = NioApiClient(
        async_get_clientsession(hass),
        token=data[CONF_TOKEN],
        vehicle_id=data[CONF_VEHICLE_ID],
        device_id=data[CONF_DEVICE_ID],
        sign=data[CONF_SIGN],
        timestamp=data[CONF_TIMESTAMP],
        app_ver=data.get(CONF_APP_VER, DEFAULT_APP_VER),
        region=data.get(CONF_REGION, DEFAULT_REGION),
    )
    try:
        await client.async_get_status()
    except NioAuthError:
        return "invalid_auth"
    except NioApiError:
        return "cannot_connect"
    return None


def _apply_credentials(base: dict[str, Any], user_input: dict[str, Any]) -> dict[str, Any]:
    """Merge a fresh token (+ any changed id fields) into a copy of ``base``."""
    data = {**base}
    for key in ID_FIELDS:
        if (value := user_input.get(key)) is not None and str(value).strip():
            data[key] = str(value).strip()
    data[CONF_TOKEN] = _clean(user_input[CONF_TOKEN])
    return data


def _credentials_schema(entry: ConfigEntry) -> vol.Schema:
    """Token (required, re-sniffed) + the id fields prefilled for easy editing."""
    d = entry.data
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN): str,
            vol.Optional(CONF_VEHICLE_ID, default=d.get(CONF_VEHICLE_ID, "")): str,
            vol.Optional(CONF_DEVICE_ID, default=d.get(CONF_DEVICE_ID, "")): str,
            vol.Optional(CONF_SIGN, default=d.get(CONF_SIGN, "")): str,
            vol.Optional(CONF_TIMESTAMP, default=d.get(CONF_TIMESTAMP, "")): str,
        }
    )


class NioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config + reauth for a NIO vehicle."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_VEHICLE_ID: user_input[CONF_VEHICLE_ID].strip(),
                CONF_DEVICE_ID: user_input[CONF_DEVICE_ID].strip(),
                CONF_SIGN: user_input[CONF_SIGN].strip(),
                CONF_TIMESTAMP: user_input[CONF_TIMESTAMP].strip(),
                CONF_TOKEN: _clean(user_input[CONF_TOKEN]),
                CONF_APP_VER: DEFAULT_APP_VER,
                CONF_REGION: DEFAULT_REGION,
                CONF_MODEL: user_input.get(CONF_MODEL, DEFAULT_MODEL),
            }
            await self.async_set_unique_id(data[CONF_VEHICLE_ID])
            self._abort_if_unique_id_configured()
            if (error := await _async_validate(self.hass, data)) is None:
                return self.async_create_entry(title=f"NIO {data[CONF_MODEL]}", data=data)
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Token expired — ask for a fresh one (ids re-enterable if they changed)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = _apply_credentials(entry.data, user_input)
            if (error := await _async_validate(self.hass, data)) is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(entry),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> NioOptionsFlow:
        return NioOptionsFlow()


def _interval(min_v: int, max_v: int, unit: str) -> NumberSelector:
    """A number-entry box (not a slider) so the value is exact and visible."""
    return NumberSelector(
        NumberSelectorConfig(
            min=min_v,
            max=max_v,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


class NioOptionsFlow(OptionsFlow):
    """Options: polling cadence + credential update."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["intervals", "credentials"]
        )

    async def async_step_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # NumberSelector yields floats; store as ints.
            return self.async_create_entry(
                data={k: int(v) for k, v in user_input.items()}
            )

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_INTERVAL_DRIVING,
                    default=opts.get(OPT_INTERVAL_DRIVING, DEFAULT_INTERVAL_DRIVING),
                ): _interval(1, 60, "min"),
                vol.Required(
                    OPT_INTERVAL_DAY,
                    default=opts.get(OPT_INTERVAL_DAY, DEFAULT_INTERVAL_DAY),
                ): _interval(5, 120, "min"),
                vol.Required(
                    OPT_INTERVAL_NIGHT,
                    default=opts.get(OPT_INTERVAL_NIGHT, DEFAULT_INTERVAL_NIGHT),
                ): _interval(5, 240, "min"),
                vol.Required(
                    OPT_DAY_START,
                    default=opts.get(OPT_DAY_START, DEFAULT_DAY_START),
                ): _interval(0, 23, "h"),
                vol.Required(
                    OPT_DAY_END,
                    default=opts.get(OPT_DAY_END, DEFAULT_DAY_END),
                ): _interval(0, 23, "h"),
            }
        )
        return self.async_show_form(step_id="intervals", data_schema=schema)

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        if user_input is not None:
            data = _apply_credentials(entry.data, user_input)
            if (error := await _async_validate(self.hass, data)) is None:
                # Persist the new credentials; the entry's update listener
                # (registered in __init__) reloads the integration to apply them.
                self.hass.config_entries.async_update_entry(entry, data=data)
                return self.async_create_entry(data=dict(entry.options))
            errors["base"] = error

        return self.async_show_form(
            step_id="credentials",
            data_schema=_credentials_schema(entry),
            errors=errors,
        )
