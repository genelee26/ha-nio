"""DataUpdateCoordinator with NIO-friendly adaptive polling.

Replaces the old "NIO: 车辆数据动态刷新" automation: poll fast while driving,
slower in the daytime, slowest overnight. The private API rate-limits (and may
even invalidate the token) if hammered, so the cadence is deliberately gentle.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import NioApiClient, NioApiError, NioAuthError, NioSignError
from .const import (
    DEFAULT_DAY_END,
    DEFAULT_DAY_START,
    DEFAULT_INTERVAL_DAY,
    DEFAULT_INTERVAL_DRIVING,
    DEFAULT_INTERVAL_NIGHT,
    DOMAIN,
    OPT_DAY_END,
    OPT_DAY_START,
    OPT_INTERVAL_DAY,
    OPT_INTERVAL_DRIVING,
    OPT_INTERVAL_NIGHT,
    VEHICLE_STATE_DRIVING,
)

_LOGGER = logging.getLogger(__name__)

type NioConfigEntry = ConfigEntry[NioDataUpdateCoordinator]


class NioDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls vehicle status and adapts the interval to vehicle state."""

    config_entry: NioConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NioConfigEntry,
        client: NioApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=self._opt(entry, OPT_INTERVAL_DAY, DEFAULT_INTERVAL_DAY)),
        )
        self.client = client

    @staticmethod
    def _opt(entry: ConfigEntry, key: str, default: int) -> int:
        return int(entry.options.get(key, default))

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.async_get_status()
        except NioSignError as err:
            # Not a token problem — the captured request stopped matching (app
            # likely updated). Surface a reauth so the user re-pastes a fresh
            # capture rather than chasing a phantom "token rejected".
            raise ConfigEntryAuthFailed(
                "NIO signature rejected — re-sniff a current status request "
                "(the app's app_ver/fields may have changed)"
            ) from err
        except NioAuthError as err:
            raise ConfigEntryAuthFailed(
                "NIO token rejected — re-sniff a fresh token from the app"
            ) from err
        except NioApiError as err:
            raise UpdateFailed(str(err)) from err

        self.update_interval = self._next_interval(data)
        _LOGGER.debug("Next NIO poll in %s", self.update_interval)
        return data

    def _next_interval(self, data: dict[str, Any]) -> timedelta:
        entry = self.config_entry
        vehicle_state = (data.get("exterior_status") or {}).get("vehicle_state")
        if vehicle_state == VEHICLE_STATE_DRIVING:
            minutes = self._opt(entry, OPT_INTERVAL_DRIVING, DEFAULT_INTERVAL_DRIVING)
        else:
            now = dt_util.now()
            day_start = self._opt(entry, OPT_DAY_START, DEFAULT_DAY_START)
            day_end = self._opt(entry, OPT_DAY_END, DEFAULT_DAY_END)
            if day_start <= now.hour < day_end:
                minutes = self._opt(entry, OPT_INTERVAL_DAY, DEFAULT_INTERVAL_DAY)
            else:
                minutes = self._opt(entry, OPT_INTERVAL_NIGHT, DEFAULT_INTERVAL_NIGHT)
        return timedelta(minutes=minutes)
