"""Async client for the NIO private vehicle-status API.

The request replays a status call sniffed from the NIO iOS app **verbatim**: the
captured query string (``field=…&app_ver=…&…&timestamp=…&sign=…``) is replayed
unchanged because the server's ``sign`` covers the whole param set. Only the
path's ``vehicle_id`` and the Bearer token are handled separately. The captured
``sign``/``timestamp`` stay valid indefinitely (the server doesn't enforce
freshness); the token is the account session credential until signed out.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from yarl import URL

from .capture import app_ver_from_query
from .const import (
    API_HOST,
    API_HOST_HEADER,
    API_STATUS_PATH,
    DEFAULT_APP_VER,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class NioApiError(Exception):
    """Generic API failure (network, 5xx, malformed payload)."""


class NioAuthError(NioApiError):
    """Token rejected — needs re-auth (re-sniff a fresh token)."""


class NioSignError(NioApiError):
    """Signature rejected — the captured request no longer matches.

    Distinct from NioAuthError: the token may be perfectly valid. This means the
    replayed ``sign`` doesn't validate against the query the server received —
    almost always because the NIO app updated (new field / new app_ver) and a
    *fresh* status request must be re-captured. Mislabelling this as a token
    failure is exactly what sent earlier users chasing the wrong problem.
    """


class NioApiClient:
    """Minimal read-only client for icar.nio.com vehicle status."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        token: str,
        vehicle_id: str,
        query: str,
    ) -> None:
        self._session = session
        self._vehicle_id = vehicle_id
        self._query = query
        # Replay verbatim — encoded=True stops yarl from re-encoding the query
        # (which would change the bytes the sign was computed over).
        self._url = URL(
            f"https://{API_HOST}{API_STATUS_PATH.format(vehicle_id=vehicle_id)}?{query}",
            encoded=True,
        )
        # Match the User-Agent's app_ver to the captured request's.
        app_ver = app_ver_from_query(query) or DEFAULT_APP_VER
        self._headers = {
            "Host": API_HOST_HEADER,
            "Accept": "application/json,text/json,text/plain",
            "User-Agent": USER_AGENT.format(app_ver=app_ver),
            "Authorization": f"Bearer {token}",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        }

    async def async_get_status(self) -> dict[str, Any]:
        """Fetch full vehicle status; return the ``data`` payload."""
        try:
            async with self._session.get(self._url, headers=self._headers) as resp:
                status = resp.status
                try:
                    payload = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    payload = None
        except aiohttp.ClientError as err:
            raise NioApiError(f"Connection error: {err}") from err

        code = (payload or {}).get("result_code")
        if code == "success":
            data = payload.get("data")
            if not isinstance(data, dict):
                raise NioApiError("Malformed response: missing data object")
            return data

        # Classify the failure so the UI/coordinator can react correctly. Check
        # sign BEFORE the generic 401/403 branch: a bad sign returns HTTP 403
        # too, but it is NOT a token problem.
        codestr = str(code)
        if code == "sign_failed" or "sign" in codestr:
            raise NioSignError(
                f"NIO rejected the signature (result_code={code}). The captured "
                "request no longer matches the server — re-sniff a current "
                "status request from the app (its app_ver/fields may have changed)."
            )
        if status == 401 or "auth" in codestr or "token" in codestr:
            raise NioAuthError(
                f"Token rejected (HTTP {status}, result_code={code})"
            )
        raise NioApiError(f"NIO API error (HTTP {status}, result_code={code})")
