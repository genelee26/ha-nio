"""Config flow for the NIO integration.

Setup is "paste one sniffed status request": the whole captured URL (or just its
``/api/2/...status?...`` path+query) plus the Authorization Bearer token. The
query is stored and replayed verbatim — NOT rebuilt from individual fields —
because the server's ``sign`` covers the entire param set, which drifts as the
app updates (see capture.py). This replaces the old per-field flow that
hard-coded ``app_ver`` and the field list and broke on every app update.

Options is a menu: polling cadence (number-entry boxes) and credentials (update
the token, optionally re-paste a fresh capture, without waiting for reauth).
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
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import NioApiClient, NioApiError, NioAuthError, NioSignError
from .capture import parse_capture
from .const import (
    CONF_MODEL,
    CONF_QUERY,
    CONF_TOKEN,
    CONF_VEHICLE_ID,
    DEFAULT_DAY_END,
    DEFAULT_DAY_START,
    DEFAULT_DEBUG,
    DEFAULT_INTERVAL_DAY,
    DEFAULT_INTERVAL_DRIVING,
    DEFAULT_INTERVAL_NIGHT,
    DEFAULT_MODEL,
    DOMAIN,
    OPT_DAY_END,
    OPT_DAY_START,
    OPT_DEBUG,
    OPT_INTERVAL_DAY,
    OPT_INTERVAL_DRIVING,
    OPT_INTERVAL_NIGHT,
)

_LOGGER = logging.getLogger(__name__)

# Transient form key for the pasted capture (not stored; split into
# vehicle_id + query before persisting).
CONF_CAPTURE = "capture"


def _capture_box() -> TextSelector:
    """Multiline text box for the long captured URL (visible, not masked)."""
    return TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True))


def _secret() -> TextSelector:
    """A masked text box with a reveal (eye) toggle — for the token."""
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAPTURE): _capture_box(),
        vol.Required(CONF_TOKEN): _secret(),
        vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): str,
    }
)


def _clean(value: str) -> str:
    """Trim and drop a stray ``Bearer `` prefix users paste with the token."""
    return value.removeprefix("Bearer ").strip()


async def _async_validate(
    hass: HomeAssistant, *, token: str, vehicle_id: str, query: str
) -> str | None:
    """Hit the API once with the given credentials; return an error key or None."""
    client = NioApiClient(
        async_get_clientsession(hass),
        token=token,
        vehicle_id=vehicle_id,
        query=query,
    )
    try:
        await client.async_get_status()
    except NioSignError:
        return "invalid_sign"
    except NioAuthError:
        return "invalid_auth"
    except NioApiError:
        return "cannot_connect"
    return None


def _credentials_schema(entry: ConfigEntry) -> vol.Schema:
    """Token (masked, prefilled) + optional fresh capture (to refresh the query)."""
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN, default=entry.data.get(CONF_TOKEN, "")): _secret(),
            vol.Optional(CONF_CAPTURE, default=""): _capture_box(),
        }
    )


class NioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config + reauth for a NIO vehicle."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = _clean(user_input[CONF_TOKEN])
            model = user_input.get(CONF_MODEL, DEFAULT_MODEL)
            try:
                vehicle_id, query = parse_capture(user_input[CONF_CAPTURE])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                await self.async_set_unique_id(vehicle_id)
                self._abort_if_unique_id_configured()
                error = await _async_validate(
                    self.hass, token=token, vehicle_id=vehicle_id, query=query
                )
                if error is None:
                    return self.async_create_entry(
                        title=f"NIO {model}",
                        data={
                            CONF_TOKEN: token,
                            CONF_VEHICLE_ID: vehicle_id,
                            CONF_QUERY: query,
                            CONF_MODEL: model,
                        },
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Token expired — ask for a fresh one (capture re-pasteable if it changed)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data, error = self._apply_credentials(entry, user_input)
            if error:
                errors["base"] = error
            else:
                error = await _async_validate(
                    self.hass,
                    token=data[CONF_TOKEN],
                    vehicle_id=data[CONF_VEHICLE_ID],
                    query=data[CONF_QUERY],
                )
                if error is None:
                    return self.async_update_reload_and_abort(entry, data=data)
                errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(entry),
            errors=errors,
        )

    @staticmethod
    def _apply_credentials(
        entry: ConfigEntry, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Merge a fresh token (+ optional re-pasted capture) into entry.data."""
        data = {**entry.data, CONF_TOKEN: _clean(user_input[CONF_TOKEN])}
        capture = (user_input.get(CONF_CAPTURE) or "").strip()
        if capture:
            try:
                vehicle_id, query = parse_capture(capture)
            except ValueError:
                return data, "invalid_url"
            data[CONF_VEHICLE_ID] = vehicle_id
            data[CONF_QUERY] = query
        return data, None

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
            step_id="init", menu_options=["intervals", "credentials", "debug"]
        )

    async def async_step_debug(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Toggle debug mode. Saving reloads the entry (update listener)."""
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, OPT_DEBUG: bool(user_input[OPT_DEBUG])}
            )
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_DEBUG,
                    default=self.config_entry.options.get(OPT_DEBUG, DEFAULT_DEBUG),
                ): bool
            }
        )
        return self.async_show_form(step_id="debug", data_schema=schema)

    async def async_step_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # NumberSelector yields floats; store as ints. Preserve other options
            # (e.g. the debug flag) so changing intervals doesn't drop them.
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    **{k: int(v) for k, v in user_input.items()},
                }
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
            data, error = NioConfigFlow._apply_credentials(entry, user_input)
            if error:
                errors["base"] = error
            else:
                error = await _async_validate(
                    self.hass,
                    token=data[CONF_TOKEN],
                    vehicle_id=data[CONF_VEHICLE_ID],
                    query=data[CONF_QUERY],
                )
                if error is None:
                    # Persist the new credentials; the entry's update listener
                    # (registered in __init__) reloads the integration.
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    return self.async_create_entry(data=dict(entry.options))
                errors["base"] = error

        return self.async_show_form(
            step_id="credentials",
            data_schema=_credentials_schema(entry),
            errors=errors,
        )
