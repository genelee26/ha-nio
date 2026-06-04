"""Async client for the NIO private vehicle-status API.

The endpoint, query parameters and headers replicate the request the NIO iOS
app makes (sniffed via MITM). The ``sign``/``timestamp`` pair is captured once
and replayed as-is — the server currently does not enforce freshness. The
Bearer token is the account session credential and stays valid until the
account is signed out remotely.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    API_APP_ID,
    API_FIELDS,
    API_HOST,
    API_HOST_HEADER,
    API_STATUS_PATH,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class NioApiError(Exception):
    """Generic API failure (network, 5xx, malformed payload)."""


class NioAuthError(NioApiError):
    """Token rejected — needs re-auth (re-sniff a fresh token)."""


class NioApiClient:
    """Minimal read-only client for icar.nio.com vehicle status."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        token: str,
        vehicle_id: str,
        device_id: str,
        sign: str,
        timestamp: str,
        app_ver: str,
        region: str,
    ) -> None:
        self._session = session
        self._vehicle_id = vehicle_id
        self._params = [
            *[("field", f) for f in API_FIELDS],
            ("app_ver", app_ver),
            ("region", region),
            ("app_id", API_APP_ID),
            ("device_id", device_id),
            ("lang", "zh-CN"),
            ("timestamp", timestamp),
            ("sign", sign),
        ]
        self._headers = {
            "Host": API_HOST_HEADER,
            "Accept": "application/json,text/json,text/plain",
            "User-Agent": USER_AGENT.format(app_ver=app_ver),
            "Authorization": f"Bearer {token}",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        }

    async def async_get_status(self) -> dict[str, Any]:
        """Fetch full vehicle status; return the ``data`` payload."""
        url = f"https://{API_HOST}{API_STATUS_PATH.format(vehicle_id=self._vehicle_id)}"
        try:
            async with self._session.get(
                url, params=self._params, headers=self._headers
            ) as resp:
                if resp.status in (401, 403):
                    raise NioAuthError(f"Token rejected (HTTP {resp.status})")
                if resp.status != 200:
                    raise NioApiError(f"HTTP {resp.status} from NIO API")
                payload = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise NioApiError(f"Connection error: {err}") from err

        if payload.get("result_code") != "success":
            code = payload.get("result_code", "<missing>")
            # NIO signals expired sessions in-band as well as via HTTP status.
            if "auth" in str(code) or "token" in str(code):
                raise NioAuthError(f"NIO result_code: {code}")
            raise NioApiError(f"NIO result_code: {code}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise NioApiError("Malformed response: missing data object")
        return data
