"""HA-free smoke tests: gcj02 conversion, URL parsing, aggregate door/window
logic against the captured fixture. Run directly: python tests/test_pure_logic.py
"""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

COMPONENT = Path(__file__).parent.parent / "custom_components" / "nio"
sys.path.insert(0, str(COMPONENT))

import const  # noqa: E402
import gcj02  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "status.json").read_text())
DATA = FIXTURE["data"]


def test_gcj02():
    # Fixture position is a public landmark (not a real owner's home) — the
    # converted result must shift by roughly 0.002-0.006 degrees and be
    # deterministic.
    pos = DATA["position_status"]
    lng, lat = gcj02.gcj02_to_wgs84(pos["longitude"], pos["latitude"])
    dlng = pos["longitude"] - lng
    dlat = pos["latitude"] - lat
    assert 0.001 < dlng < 0.01, f"unexpected lng delta {dlng}"
    assert 0.001 < abs(dlat) < 0.01, f"unexpected lat delta {dlat}"
    # Matches the legacy update_nio_location.py output (same algorithm).
    assert (lng, lat) == gcj02.gcj02_to_wgs84(pos["longitude"], pos["latitude"])
    print(f"  gcj02: ({pos['latitude']:.6f},{pos['longitude']:.6f}) -> ({lat},{lng})")


def test_url_parse():
    # Replicates config_flow._parse_status_url without importing HA.
    # Example values only — not real credentials.
    url = (
        "https://icar.nio.com/api/2/rvs/vehicle/0000000000000000000000000000abcd/status"
        "?field=soc&app_ver=6.3.0&region=cn&app_id=10002"
        "&device_id=00000000000000000000000000000000&lang=zh-CN"
        "&timestamp=1773732007&sign=0000000000000000000000000000000a"
    )
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    vehicle_id = parts[parts.index("vehicle") + 1]
    qs = parse_qs(parsed.query)
    assert vehicle_id == "0000000000000000000000000000abcd"
    assert qs["device_id"][0] == "00000000000000000000000000000000"
    assert qs["sign"][0] == "0000000000000000000000000000000a"
    print(f"  url parse: vehicle_id={vehicle_id}")


def test_door_window_logic():
    doors = DATA["door_status"]
    values = [doors.get(f) for f in const.DOOR_AJAR_FIELDS]
    assert not any(v is None for v in values), "fixture missing ajar fields"
    any_open = any(v not in (None, 0, const.DOOR_CLOSED) for v in values)
    assert any_open is False, "fixture car has all doors closed (all == 1)"

    windows = DATA["window_status"]
    wvalues = [windows.get(f) for f in const.WINDOW_POSN_FIELDS]
    assert any(v not in (None, 0) for v in wvalues) is False
    print(f"  doors={values} windows={wvalues} -> all closed ✓")


def test_vehicle_state_and_soc():
    assert DATA["exterior_status"]["vehicle_state"] == const.VEHICLE_STATE_PARKED
    soc = DATA["soc_status"]
    rate = round(soc["remaining_actual_range"] / soc["remaining_range"] * 100, 1)
    assert rate == 68.6, rate
    print(f"  soc={soc['soc']}% rate={rate}%")


if __name__ == "__main__":
    for fn in (test_gcj02, test_url_parse, test_door_window_logic, test_vehicle_state_and_soc):
        print(f"{fn.__name__}:")
        fn()
    print("ALL PURE-LOGIC TESTS PASSED")
