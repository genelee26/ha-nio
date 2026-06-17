"""Constants for the NIO integration."""

from __future__ import annotations

DOMAIN = "nio"

# Bundled static assets (map marker logo) served by the integration itself.
STATIC_URL_BASE = "/nio_static"
ENTITY_PICTURE = f"{STATIC_URL_BASE}/nio_logo.png"

# --- Config entry data keys (v2: the whole sniffed request, replayed verbatim) ---
CONF_TOKEN = "token"
CONF_VEHICLE_ID = "vehicle_id"
# The verbatim status-request query string (everything after the URL's '?').
# Replayed byte-for-byte because the server's sign covers the entire param set
# (field list + order, app_ver, device_id, timestamp, …) — see capture.py.
CONF_QUERY = "query"
CONF_MODEL = "model"

# --- Legacy v1 data keys (per-field). Read only by the migration in __init__. ---
CONF_DEVICE_ID = "device_id"
CONF_SIGN = "sign"
CONF_TIMESTAMP = "timestamp"
CONF_APP_VER = "app_ver"
CONF_REGION = "region"

DEFAULT_APP_VER = "6.3.0"
DEFAULT_REGION = "cn"
DEFAULT_MODEL = "EC6"

# --- Options (polling cadence, minutes) ---
OPT_INTERVAL_DRIVING = "interval_driving"
OPT_INTERVAL_DAY = "interval_day"
OPT_INTERVAL_NIGHT = "interval_night"
OPT_DAY_START = "day_start_hour"
OPT_DAY_END = "day_end_hour"

DEFAULT_INTERVAL_DRIVING = 5
DEFAULT_INTERVAL_DAY = 15
DEFAULT_INTERVAL_NIGHT = 30
DEFAULT_DAY_START = 7
DEFAULT_DAY_END = 19

# --- NIO private API (as captured from the iOS app) ---
API_HOST = "icar.nio.com"
API_STATUS_PATH = "/api/2/rvs/vehicle/{vehicle_id}/status"
API_HOST_HEADER = "tsp.nio.com"
API_APP_ID = "10002"
USER_AGENT = (
    "NextevCar/{app_ver} (com.do1.WeiLaiApp; build:2586; iOS 26.2.1) "
    "Alamofire/5.9.1"
)

# NOTE: requests are no longer *built* from these — v2 replays the captured
# query verbatim (see capture.py / api.py). API_FIELDS + API_APP_ID survive only
# so the v1→v2 migration can reconstruct the exact query the old client sent
# (which the old, matching sign still validates). Order is load-bearing there.
API_FIELDS = [
    "heating",
    "fota",
    "offcar_power_swap_status",
    "connection",
    "remote_operate_status",
    "maintain",
    "nearby_car_ctrl",
    "box",
    "lv_batt",
    "exterior",
    "special",
    "position",
    "power_swap_order",
    "door",
    "window",
    "soc",
    "mix_auth",
    "trip_share_status",
    "device_status",
    "offcar_mode_status",
    "light",
    "tyre",
    "hvac",
    "frdg",
    "charge_status_order",
]

# exterior_status.vehicle_state observed values
VEHICLE_STATE_DRIVING = 1
VEHICLE_STATE_PARKED = 2
VEHICLE_STATE_RESTING = 3
VEHICLE_STATES = {
    VEHICLE_STATE_DRIVING: "driving",
    VEHICLE_STATE_PARKED: "parked",
    VEHICLE_STATE_RESTING: "resting",
}

# door_status *_ajar_status values (field-tested 2026-06-06, all 5 openings):
# 1 = closed, 0 = open. vehicle_lock_status: 1 = locked, 0 = unlocked.
DOOR_CLOSED = 1
LOCK_LOCKED = 1

DOOR_AJAR_FIELDS = [
    "door_ajar_front_left_status",
    "door_ajar_front_right_status",
    "door_ajar_rear_left_status",
    "door_ajar_rear_right_status",
    "tailgate_ajar_status",
]

WINDOW_POSN_FIELDS = [
    "win_front_left_posn",
    "win_front_right_posn",
    "win_rear_left_posn",
    "win_rear_right_posn",
]

# --- Service-order / billing API (gateway-front-external; shares the account
# token). Unlike the status API this gateway does NOT verify a sign — it only
# enforces timestamp freshness, which the NIO User-Agent bypasses. Read-only. ---
ORDERS_API_URL = (
    "https://gateway-front-external.nio.com/moat/1100367/api/v1/otd/car/ext"
    "/general/serviceOrder/getTabOrder"
)
ORDERS_USER_AGENT = "NextevCar/6.3.0 (com.do1.WeiLaiApp; build:2586; iOS 26.2.1)"
ORDERS_PAGE_SIZE = 50  # initial backfill: 50/page, paginate until hasMore=false
ORDERS_RECENT_LIMIT = 10  # steady state: re-fetch the most recent 10 and upsert

# orderType → display name (the 8 service-order kinds; comma-joined, no spaces).
ORDER_TYPES = {
    "pe_shaman": "充电",
    "pe_shaman_change": "换电",
    "service_pe_discharge": "放电",
    "battery_flexible_upgrade": "灵活升级",
    "nsom_so_maintenance": "一键维保",
    "nsom_so_chauffeur": "驾享服务",
    "chauffeur_vehicle_delivery": "一键送车",
    "so_case_accident": "事故报案",
}
ORDER_TYPE_SWAP = "pe_shaman_change"
ORDER_TYPE_MAINTENANCE = "nsom_so_maintenance"
# orderNo + createTime are the only immutable fields; everything else (status,
# payment, price, …) can change on later fetches, so orders are upserted by
# orderNo. A status name containing this mark means the order was cancelled and
# must be excluded from swap counts/cost.
ORDER_STATUS_CANCELLED_MARK = "取消"

# Long-term statistics object-ids. The HA layer prefixes the "nio:" source to
# register these as external statistics, backfilled from each order's real
# createTime so the history predates the integration install.
STAT_SWAP_COST = "battery_swap_cost"
STAT_SWAP_COUNT = "battery_swap_count"

# Static query params for the orders request (offset/limit/orderTypes added per
# call). No sign ⇒ param order and encoding don't matter to the server; these
# mirror a captured request. region=US is harmless (still returns domestic).
ORDERS_QUERY_STATIC = {
    "hash_type": "sha256",
    "lang": "zh",
    "region": "US",
    "tz_offset": "28800",
    "nioAppVersion": "6.5.3",
    "appVersion": "5.31.0",
    "orderConfVersion": "5.31.0",
    "app_ver": "6.5.3",
    "inProgressStatus": "false",
    "pagination_method": "2",
}
ORDERS_ORDER_TYPES_PARAM = ",".join(ORDER_TYPES)  # all 8 kinds, comma-joined

# Orders coordinator cadence + one-time backfill throttle.
OPT_INTERVAL_ORDERS = "interval_orders_hours"
DEFAULT_INTERVAL_ORDERS = 12  # steady-state refresh of the recent window (hours)
BACKFILL_PAGE_GAP = 600  # seconds between backfill pages — gentle on the API
ORDERS_STORAGE_VERSION = 1

# --- Debug mode (option). When on: injected debug orders show + count in the
# popup/sensors, and the refresh buttons prompt to download diagnostics (which
# carry the last raw server responses). Debug orders never enter long-term
# statistics, and are hidden + uncounted when debug is off (still in .storage). ---
OPT_DEBUG = "debug"
DEFAULT_DEBUG = False
