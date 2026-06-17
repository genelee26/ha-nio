"""HA-free service-order (billing) ledger logic.

``serviceOrder/getTabOrder`` returns the car's service orders (battery swaps,
maintenance, …). Two fields are immutable — ``orderNo`` (identity) and
``createTime`` — while everything else (status, payment, price) can change on a
later fetch: "换电已完成，未支付" → "…已支付", or a swap → "已取消". So orders are kept
in a ledger keyed by ``orderNo`` and **upserted**, not appended; every snapshot
and statistic is *derived* from that ledger, so a later mutation (even a
cancellation) re-derives correctly.

Import-light (only ``const`` + stdlib) so the coordinator and the HA-free tests
can share it. The HTTP client and the HA entities live elsewhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

try:  # package context (inside Home Assistant)
    from . import const
except ImportError:  # pragma: no cover - HA-free test imports it top-level
    import const  # type: ignore[no-redefine]

_HOUR_MS = 3_600_000
# Orders are billed and displayed in China time; month boundaries follow it.
CST = timezone(timedelta(hours=8))


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_order(raw: dict) -> dict:
    """Project a raw API order onto the curated, type-coerced ledger shape.

    Keeps only what the snapshots/statistics need; PII like ``vinCode`` is
    intentionally dropped so the ledger persisted in ``.storage`` stays lean.
    """
    return {
        "orderNo": str(raw.get("orderNo") or ""),
        "createTime": int(raw.get("createTime") or 0),
        "orderType": raw.get("orderType"),
        "orderName": raw.get("orderName"),
        "orderStatus": raw.get("orderStatus"),
        "orderStatusName": raw.get("orderStatusName"),
        "paymentStatus": raw.get("paymentStatus"),
        "priceCash": _to_float(raw.get("priceCash")),
        "payDesc": raw.get("payDesc"),
        "station": raw.get("resourceAddress") or raw.get("address"),
    }


def is_cancelled(order: dict) -> bool:
    return const.ORDER_STATUS_CANCELLED_MARK in (order.get("orderStatusName") or "")


def is_swap(order: dict) -> bool:
    return order.get("orderType") == const.ORDER_TYPE_SWAP


def _counted_swap(order: dict) -> bool:
    """A swap that actually happened (cancelled attempts don't count)."""
    return is_swap(order) and not is_cancelled(order)


def _swap_cost(order: dict) -> float:
    """Cost a counted swap contributes (price-less / not-yet-priced ⇒ 0)."""
    return order.get("priceCash") or 0.0


def merge_into_ledger(
    ledger: dict[str, dict], fetched: list[dict]
) -> tuple[dict[str, dict], int | None]:
    """Upsert fetched orders into the ledger (insert new, overwrite changed).

    Returns ``(new_ledger, dirty_since)`` where ``dirty_since`` is the earliest
    ``createTime`` among inserted-or-changed orders, or ``None`` if nothing
    changed. The caller re-imports statistics from that hour forward — cheap
    because mutations land on recent orders, but correct even when an old order
    changes (every cumulative sum after it shifts). The ledger is never pruned;
    orders don't disappear, they only change status (e.g. → cancelled).
    """
    new = dict(ledger)
    dirty: list[int] = []
    for raw in fetched:
        order = normalize_order(raw)
        order_no = order["orderNo"]
        if not order_no:
            continue
        if new.get(order_no) != order:
            new[order_no] = order
            dirty.append(order["createTime"])
    return new, (min(dirty) if dirty else None)


def _year_month(create_ms: int) -> tuple[int, int]:
    dt = datetime.fromtimestamp(create_ms / 1000, CST)
    return dt.year, dt.month


def aggregate(ledger: dict[str, dict], now_ms: int | None = None) -> dict[str, Any]:
    """Derive snapshot values from the ledger: totals, the latest swap, month.

    Cancelled swaps are excluded from counts and cost. Passing ``now_ms`` adds
    the current-month figures, computed in China time.
    """
    swaps = [o for o in ledger.values() if _counted_swap(o)]
    swaps_desc = sorted(swaps, key=lambda o: o["createTime"], reverse=True)
    last = swaps_desc[0] if swaps_desc else None

    result: dict[str, Any] = {
        "swap_count": len(swaps),
        "swap_total_cost": round(sum(_swap_cost(o) for o in swaps), 2),
        "swap_last_time": last["createTime"] if last else None,
        "swap_last_cost": last["priceCash"] if last else None,
        "swap_last_station": last["station"] if last else None,
        "swap_last_status": last["orderStatusName"] if last else None,
    }

    maint = [
        o
        for o in ledger.values()
        if o.get("orderType") == const.ORDER_TYPE_MAINTENANCE and not is_cancelled(o)
    ]
    maint_desc = sorted(maint, key=lambda o: o["createTime"], reverse=True)
    result["maintenance_count"] = len(maint)
    result["maintenance_last_time"] = (
        maint_desc[0]["createTime"] if maint_desc else None
    )

    if now_ms is not None:
        this_month = _year_month(now_ms)
        month_swaps = [o for o in swaps if _year_month(o["createTime"]) == this_month]
        result["swap_month_count"] = len(month_swaps)
        result["swap_month_cost"] = round(sum(_swap_cost(o) for o in month_swaps), 2)

    return result


def build_orders_response(
    ledger: dict[str, dict], now_ms: int, include_cancelled: bool = True
) -> dict[str, Any]:
    """Full detail payload for the ``get_service_orders`` service / card popup.

    The aggregate summary plus every order, **newest-first**. Cancelled orders
    are kept (the popup shows them struck-through, flagged by orderStatusName)
    unless ``include_cancelled`` is False. The card does month/order navigation
    client-side over this one list, so the service returns everything at once.
    """
    orders = sorted(ledger.values(), key=lambda o: o["createTime"], reverse=True)
    if not include_cancelled:
        orders = [o for o in orders if not is_cancelled(o)]
    return {
        "summary": aggregate(ledger, now_ms=now_ms),
        "orders": orders,
        "order_total": len(ledger),
    }


def _floor_hour(create_ms: int) -> int:
    return (create_ms // _HOUR_MS) * _HOUR_MS


def build_stat_points(
    ledger: dict[str, dict], since_ms: int | None = None
) -> dict[str, list[tuple[int, float]]]:
    """Build hour-aligned cumulative cost/count series over counted swaps.

    Each series is the running total summed per UTC hour, keyed by the hour-start
    epoch ms. The ``sum`` at each hour always reflects *all* prior history, so
    when ``since_ms`` trims the output to a recent tail (after a mutation) the
    first emitted point still carries the full cumulative total — HA overwrites
    only those hours and keeps the earlier ones. Idempotent: same ledger → same
    points.
    """
    swaps = sorted(
        (o for o in ledger.values() if _counted_swap(o)),
        key=lambda o: o["createTime"],
    )
    cost_run = 0.0
    count_run = 0
    cost_by_hour: dict[int, float] = {}
    count_by_hour: dict[int, int] = {}
    for order in swaps:
        hour = _floor_hour(order["createTime"])
        cost_run += _swap_cost(order)
        count_run += 1
        cost_by_hour[hour] = round(cost_run, 2)
        count_by_hour[hour] = count_run

    floor_since = _floor_hour(since_ms) if since_ms is not None else None

    def _emit(by_hour: dict[int, Any]) -> list[tuple[int, float]]:
        return [
            (hour, by_hour[hour])
            for hour in sorted(by_hour)
            if floor_since is None or hour >= floor_since
        ]

    return {
        const.STAT_SWAP_COST: _emit(cost_by_hour),
        const.STAT_SWAP_COUNT: _emit(count_by_hour),
    }


# --- Request / response helpers (pure; the aiohttp client in api.py uses them) ---


def build_orders_query(offset: int, limit: int) -> str:
    """Build the getTabOrder query string for one page.

    Commas in ``orderTypes`` stay literal — the gateway verifies no sign, so
    encoding is free, and literal commas match the request shape verified to
    work. Param order is irrelevant for the same (no-sign) reason.
    """
    params = dict(const.ORDERS_QUERY_STATIC)
    params["orderTypes"] = const.ORDERS_ORDER_TYPES_PARAM
    params["offset"] = str(offset)
    params["limit"] = str(limit)
    return "&".join(f"{key}={value}" for key, value in params.items())


def classify_orders_result(payload: dict | None, http_status: int) -> str:
    """Classify a getTabOrder response → ``"ok"`` / ``"auth"`` / ``"error"``.

    Success is ``resultCode == "0000"``. A rejected token shows up as an auth
    code/message or HTTP 401/403 — surfaced as ``"auth"`` so the client raises
    NioAuthError and the entry re-auths (same token as the status API).
    """
    payload = payload or {}
    code = str(payload.get("resultCode") or payload.get("result_code") or "")
    if code in ("0000", "success"):
        return "ok"
    msg = str(payload.get("resultMsg") or payload.get("debug_msg") or "")
    blob = f"{code} {msg}".lower()
    if http_status in (401, 403) or any(
        marker in blob for marker in ("auth", "token", "login", "unauthor")
    ):
        return "auth"
    return "error"


def extract_orders(payload: dict | None) -> tuple[list[dict], bool]:
    """Pull ``(orders, has_more)`` out of a successful getTabOrder payload."""
    result_data = (payload or {}).get("resultData") or {}
    return (result_data.get("data") or []), bool(result_data.get("hasMore"))
