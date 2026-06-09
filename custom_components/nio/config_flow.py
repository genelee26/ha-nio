"""Config flow for the NIO integration.

Setup is "paste what you sniffed": the full status request URL from the NIO
iOS app plus the Bearer token. vehicle_id / device_id / sign / timestamp /
app_ver / region are all parsed out of the URL, validated with a live API
call, then stored in the config entry (no more plaintext YAML).

Options is a menu: polling cadence (number-entry boxes) and credentials
(update the token / re-paste the URL without waiting for a reauth prompt).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
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


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> str | None:
    """Hit the API once with the given credentials; return an error key or None."""
    client = NioApiClient(
        async_get_clientsession(hass),
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


def _apply_credentials(
    base: dict[str, Any], user_input: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Merge a token (+ optional re-pasted URL) into a copy of ``base``.

    Returns (new_data, error_key). error_key is set only on a bad URL.
    """
    data = {**base}
    if url := user_input.get(CONF_STATUS_URL):
        try:
            data.update(_parse_status_url(url))
        except ValueError:
            return data, "invalid_url"
    data[CONF_TOKEN] = user_input[CONF_TOKEN].removeprefix("Bearer ").strip()
    return data, None


class NioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config + reauth for a NIO vehicle."""

    VERSION = 1

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
                if (error := await _async_validate(self.hass, data)) is None:
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
            data, errors_key = _apply_credentials(entry.data, user_input)
            if errors_key:
                errors["base"] = errors_key
            elif (error := await _async_validate(self.hass, data)) is None:
                return self.async_update_reload_and_abort(entry, data=data)
            else:
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
            data, errors_key = _apply_credentials(entry.data, user_input)
            if errors_key:
                errors["base"] = errors_key
            elif (error := await _async_validate(self.hass, data)) is None:
                # Persist the new credentials; the entry's update listener
                # (registered in __init__) reloads the integration to apply them.
                self.hass.config_entries.async_update_entry(entry, data=data)
                return self.async_create_entry(data=dict(entry.options))
            else:
                errors["base"] = error

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): str,
                    vol.Optional(CONF_STATUS_URL): str,
                }
            ),
            errors=errors,
        )
