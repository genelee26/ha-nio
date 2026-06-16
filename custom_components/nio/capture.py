"""HA-free helpers for the sniffed NIO status request.

The server's ``sign`` covers the *entire* status query string — the field list
(set **and** order), ``app_ver``, ``device_id``, ``timestamp`` and so on. Every
one of those drifts as the NIO app updates (6.6.0 added ``field=key`` and
reordered fields; ``app_ver`` differs per user). So the only robust approach is
to capture one real status request and **replay its query byte-for-byte** — no
reconstruction from individual fields. This module parses a pasted capture into
``(vehicle_id, query)`` and rebuilds the legacy v1 query for migration.

Kept import-light (only ``const``) so the config flow, the ``__init__``
migration and the HA-free tests can all share it.
"""

from __future__ import annotations

import re

try:  # package context (inside Home Assistant)
    from . import const
except ImportError:  # pragma: no cover - HA-free test imports it top-level
    import const  # type: ignore[no-redefine]

# vehicle_id sits in the path: /api/2/rvs/vehicle/<id>/status
_VEHICLE_ID_RE = re.compile(r"/vehicle/([^/?#]+)/status")
_APP_VER_RE = re.compile(r"(?:^|&)app_ver=([^&]+)")


def parse_capture(raw: str) -> tuple[str, str]:
    """Split a pasted status request into ``(vehicle_id, query)``.

    Accepts a full URL or just the ``/api/2/...status?...`` path+query. The
    host is irrelevant (the client always targets ``icar.nio.com`` with the
    ``tsp.nio.com`` Host header); only the path's vehicle_id and the query
    string after ``?`` are used. The query is returned verbatim — do not
    re-encode it, or the sign breaks.

    Raises ``ValueError`` if it doesn't look like a status request (no
    vehicle_id, no query, or missing the sign/timestamp the request needs).
    """
    text = (raw or "").strip().strip("\"'")
    if not text:
        raise ValueError("empty capture")

    vid_match = _VEHICLE_ID_RE.search(text)
    if not vid_match:
        raise ValueError("no /vehicle/<id>/status segment found")
    vehicle_id = vid_match.group(1)

    if "?" not in text:
        raise ValueError("no query string (nothing after '?')")
    query = text.split("?", 1)[1]
    # A URL query never contains raw whitespace or a fragment, so cut at the
    # first of those. This tolerates pasting a whole proxy "request line"
    # (e.g. "GET https://…/status?…&sign=x HTTP/2") or a URL followed by header
    # lines — keep just the query and drop the trailing junk.
    query = re.split(r"[\s#]", query, maxsplit=1)[0].strip()

    if not query:
        raise ValueError("empty query string")
    if "sign=" not in query or "timestamp=" not in query:
        raise ValueError("query missing sign/timestamp — not a signed status request")

    return vehicle_id, query


def app_ver_from_query(query: str) -> str | None:
    """Pull ``app_ver`` out of a query string (for the matching User-Agent)."""
    match = _APP_VER_RE.search(query or "")
    return match.group(1) if match else None


def reconstruct_query_v1(data: dict) -> str:
    """Rebuild the exact query string the v1 client sent, for v1→v2 migration.

    The old ``api.py`` passed an ordered param list to aiohttp:
    ``field=…`` (one per ``API_FIELDS``, in order), then app_ver, region,
    app_id, device_id, lang=zh-CN, timestamp, sign. All values are URL-safe
    (hex ids / digits / field names) so aiohttp emitted them unencoded — this
    join reproduces that byte-for-byte, and the user's still-valid sign keeps
    matching it. Do not change the order.
    """
    app_ver = data.get(const.CONF_APP_VER, const.DEFAULT_APP_VER)
    region = data.get(const.CONF_REGION, const.DEFAULT_REGION)
    parts = [f"field={f}" for f in const.API_FIELDS]
    parts += [
        f"app_ver={app_ver}",
        f"region={region}",
        f"app_id={const.API_APP_ID}",
        f"device_id={data[const.CONF_DEVICE_ID]}",
        "lang=zh-CN",
        f"timestamp={data[const.CONF_TIMESTAMP]}",
        f"sign={data[const.CONF_SIGN]}",
    ]
    return "&".join(parts)
