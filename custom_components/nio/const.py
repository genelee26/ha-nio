"""Constants for the NIO integration."""

from __future__ import annotations

DOMAIN = "nio"

# Bundled static assets (map marker logo) served by the integration itself.
STATIC_URL_BASE = "/nio_static"
ENTITY_PICTURE = f"{STATIC_URL_BASE}/nio_logo.png"

# --- Config entry data keys (parsed from the sniffed app request) ---
CONF_TOKEN = "token"
CONF_VEHICLE_ID = "vehicle_id"
CONF_DEVICE_ID = "device_id"
CONF_SIGN = "sign"
CONF_TIMESTAMP = "timestamp"
CONF_APP_VER = "app_ver"
CONF_REGION = "region"
CONF_MODEL = "model"

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

# All fields fetched in a single round trip (matches the app's own request).
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
