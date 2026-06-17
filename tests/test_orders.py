"""HA-free tests for the service-order ledger logic (orders.py).

Covers: upsert by orderNo, cancelled-swap exclusion (incl. the real 2026-02-02
cancel→retry same-day pair), retroactive cancellation, aggregate totals +
current-month, and the cumulative statistics series (full + dirty-tail).
Run directly:  python tests/test_orders.py
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "nio"
sys.path.insert(0, str(COMPONENT))

import const  # noqa: E402
import orders  # noqa: E402

RAW = json.loads(
    (Path(__file__).parent / "fixtures" / "orders.json").read_text(encoding="utf-8")
)
DATA = RAW["resultData"]["data"]

CST = timezone(timedelta(hours=8))


def _ms(y, mo, d, h, mi):
    """China-time wall clock → epoch ms (mirrors the fixture generator)."""
    return int(datetime(y, mo, d, h, mi, tzinfo=CST).timestamp() * 1000)


def _find(data, order_no):
    return next(o for o in data if o["orderNo"] == order_no)


def _fresh_ledger():
    ledger, _ = orders.merge_into_ledger({}, DATA)
    return ledger


def test_merge_upsert_and_dirty():
    ledger, dirty = orders.merge_into_ledger({}, DATA)
    assert len(ledger) == 6, "all six orders ingested, keyed by orderNo"
    assert dirty == _ms(2025, 12, 15, 8, 0), "dirty_since = earliest createTime"

    # Re-merging identical data is a no-op.
    ledger2, dirty2 = orders.merge_into_ledger(ledger, DATA)
    assert dirty2 is None and ledger2 == ledger, "no change ⇒ no dirty"

    # A field mutation on one existing order (未支付 → 已支付) is detected, and
    # dirty_since points at that order's (immutable) createTime.
    paid = dict(_find(DATA, "FAKE000000000006"))
    paid["orderStatusName"] = "换电已完成，已支付"
    paid["paymentStatus"] = "paid"
    ledger3, dirty3 = orders.merge_into_ledger(ledger, [paid])
    assert dirty3 == _ms(2026, 2, 15, 12, 0)
    assert ledger3["FAKE000000000006"]["orderStatusName"] == "换电已完成，已支付"
    print("  upsert + dirty tracking ✓")


def test_cancelled_excluded_same_day_pair():
    agg = orders.aggregate(_fresh_ledger())
    # 5 swap-type orders exist but one (2026-02-02 23:10) is cancelled.
    assert agg["swap_count"] == 4, "cancelled swap not counted"
    # Same-day pair: only the 23:23 completed swap counts, not the 23:10 cancel.
    assert agg["swap_total_cost"] == 190.58
    # Most recent counted swap is 2026-02-15 (the unpaid one), not maintenance.
    assert agg["swap_last_time"] == _ms(2026, 2, 15, 12, 0)
    assert agg["maintenance_count"] == 1
    print("  cancelled excluded + same-day pair ✓")


def test_cancellation_after_record():
    # A previously-counted paid swap later flips to cancelled (e.g. refund) →
    # re-derive drops it from both count and cost.
    ledger = _fresh_ledger()
    cancelled = dict(ledger["FAKE000000003605"])
    cancelled["orderStatusName"] = "已取消，欢迎反馈"
    cancelled["priceCash"] = None
    ledger2, dirty = orders.merge_into_ledger(ledger, [cancelled])
    assert dirty == _ms(2026, 2, 2, 23, 23)
    agg = orders.aggregate(ledger2)
    assert agg["swap_count"] == 3, "cancelled-after-the-fact swap removed"
    assert agg["swap_total_cost"] == 142.0
    print("  retroactive cancellation re-derives ✓")


def test_month():
    agg = orders.aggregate(_fresh_ledger(), now_ms=_ms(2026, 2, 28, 12, 0))
    assert agg["swap_month_count"] == 2, "Feb has 2 counted swaps (cancel excluded)"
    assert agg["swap_month_cost"] == 95.58
    print("  current-month figures ✓")


def test_stat_points_cumulative_and_tail():
    ledger = _fresh_ledger()
    pts = orders.build_stat_points(ledger)
    cost = pts[const.STAT_SWAP_COST]
    count = pts[const.STAT_SWAP_COUNT]
    # One point per distinct swap hour (4 counted swaps, all different hours).
    assert len(cost) == 4 and len(count) == 4
    # Monotonic, hour-aligned, and the final sum equals the totals.
    assert [v for _, v in count] == [1, 2, 3, 4]
    assert cost[-1][1] == 190.58
    assert all(h % 3_600_000 == 0 for h, _ in cost), "hour-aligned"

    # Dirty-tail: re-importing from the last swap's hour yields a single point
    # that still carries the full cumulative total (continuity preserved).
    since = _ms(2026, 2, 15, 12, 0)
    tail = orders.build_stat_points(ledger, since_ms=since)
    assert len(tail[const.STAT_SWAP_COST]) == 1
    assert tail[const.STAT_SWAP_COST][0][1] == 190.58
    assert tail[const.STAT_SWAP_COUNT][0][1] == 4
    print("  cumulative statistics + dirty-tail ✓")


def test_build_orders_response():
    ledger = _fresh_ledger()
    resp = orders.build_orders_response(ledger, now_ms=_ms(2026, 2, 28, 12, 0))
    assert resp["order_total"] == 6
    # newest-first, every order present (incl. the cancelled one by default).
    times = [o["createTime"] for o in resp["orders"]]
    assert times == sorted(times, reverse=True), "orders sorted newest-first"
    assert len(resp["orders"]) == 6
    assert resp["summary"]["swap_count"] == 4  # aggregate carried through

    # include_cancelled=False drops the one cancelled order from the list (but
    # the summary still counts only non-cancelled swaps either way).
    resp2 = orders.build_orders_response(
        ledger, now_ms=_ms(2026, 2, 28, 12, 0), include_cancelled=False
    )
    assert len(resp2["orders"]) == 5
    assert not any(orders.is_cancelled(o) for o in resp2["orders"])
    print("  build_orders_response ✓")


def test_build_orders_query():
    q = orders.build_orders_query(0, 50)
    assert " " not in q, "no spaces in the query"
    assert "offset=0" in q and "limit=50" in q
    # orderTypes is all 8 kinds, comma-joined with literal commas.
    assert "orderTypes=pe_shaman,pe_shaman_change," in q
    assert q.count("orderTypes=") == 1
    for order_type in const.ORDER_TYPES:
        assert order_type in q, f"missing orderType {order_type}"
    assert "pagination_method=2" in q and "inProgressStatus=false" in q
    print("  query builder ✓")


def test_response_classify_and_extract():
    ok = {"resultCode": "0000", "resultData": {"data": [{"orderNo": "x"}], "hasMore": True}}
    assert orders.classify_orders_result(ok, 200) == "ok"
    data, more = orders.extract_orders(ok)
    assert len(data) == 1 and more is True

    # Rejected token: by code/message or by HTTP 401/403.
    assert orders.classify_orders_result({"resultCode": "4030", "resultMsg": "auth failed"}, 403) == "auth"
    assert orders.classify_orders_result({}, 401) == "auth"
    # Generic non-auth error stays "error" (won't trigger a needless reauth).
    assert orders.classify_orders_result({"resultCode": "5000", "resultMsg": "oops"}, 200) == "error"
    # Missing/empty data degrades gracefully.
    empty, more2 = orders.extract_orders({"resultData": {}})
    assert empty == [] and more2 is False
    print("  response classify/extract ✓")


if __name__ == "__main__":
    for fn in (
        test_merge_upsert_and_dirty,
        test_cancelled_excluded_same_day_pair,
        test_cancellation_after_record,
        test_month,
        test_stat_points_cumulative_and_tail,
        test_build_orders_response,
        test_build_orders_query,
        test_response_classify_and_extract,
    ):
        print(f"{fn.__name__}:")
        fn()
    print("ALL ORDERS TESTS PASSED")
