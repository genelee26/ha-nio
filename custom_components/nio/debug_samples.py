"""Built-in debug-order samples for the ``nio.inject_debug_order`` service.

Each value is a *raw* order dict in the shape ``getTabOrder`` returns, so
injecting one exercises the real ``normalize_order`` path. Used (developer-only)
to test rendering/aggregation of order shapes the dev account doesn't have —
e.g. the flexible-upgrade order (two stations, fee in ``extendInfo``). Injected
orders are flagged ``debug`` and only show when debug mode is on.
"""

from __future__ import annotations

# orderType -> a representative raw order. Add one per order type as samples are
# collected. createTime is left at 0 here; the inject service stamps "now" so the
# sample lands in the current month.
DEBUG_SAMPLES: dict[str, dict] = {
    "flexible_upgrade": {
        "orderType": "battery_flexible_upgrade",
        "orderName": "灵活升级",
        "createTime": 0,
        "orderStatus": "1000",
        "orderStatusName": "服务已完成",
        "orderNo": "DEBUGFLEX00000001",
        "paymentStatus": "4",
        "pickUpName": "G1京哈高速沈阳世代车城 蔚来换电站",
        "returnName": "大连甘井子区政府北 蔚来换电站",
        "oipStatus": 2,
        "extendInfo": {
            "batteryCapSeries": 3,
            "targetBatteryCapLevel": 2,
            "batteryCapLevel": 1,
            "targetBatteryCapSeries": 2,
            "paymentInfo": [
                {"amount": 83, "name": "长续航（100kWh）按月灵活升级费用", "type": 5}
            ],
            "payInArrears": False,
        },
    },
}
