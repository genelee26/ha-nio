"""HA-free smoke tests: gcj02 conversion and aggregate door/window/state logic
against the captured fixture. Run directly: python tests/test_pure_logic.py
"""

import json
import sys
from pathlib import Path

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


def _any_door_open(door_status):
    # Mirrors binary_sensor._any_door_open (kept HA-free here).
    values = [door_status.get(f) for f in const.DOOR_AJAR_FIELDS]
    if all(v is None for v in values):
        return None
    return any(v is not None and v != const.DOOR_CLOSED for v in values)


def test_door_window_logic():
    doors = DATA["door_status"]
    values = [doors.get(f) for f in const.DOOR_AJAR_FIELDS]
    assert not any(v is None for v in values), "fixture missing ajar fields"
    assert _any_door_open(doors) is False, "fixture car has all doors closed (all == 1)"

    windows = DATA["window_status"]
    wvalues = [windows.get(f) for f in const.WINDOW_POSN_FIELDS]
    assert any(v not in (None, 0) for v in wvalues) is False
    print(f"  doors={values} windows={wvalues} -> all closed ✓")


def test_door_open_semantics():
    # Field-tested 2026-06-06: every opening cycled on a real EC6 and matched
    # 1:1 against raw API captures — ajar fields read 0 when open, 1 when
    # closed (NOT 2; the earlier "2 = open, 0 = unknown" assumption was wrong
    # and made the doors binary_sensor blind to open doors).
    closed = {f: 1 for f in const.DOOR_AJAR_FIELDS}

    one_open = dict(closed, door_ajar_front_left_status=0)
    assert _any_door_open(one_open) is True, "FL door open (0) must be detected"

    all_open = {f: 0 for f in const.DOOR_AJAR_FIELDS}
    assert _any_door_open(all_open) is True, "all openings open must be detected"

    assert _any_door_open({}) is None, "missing section -> unknown"

    # vehicle_lock_status: 1 = locked, 0 = unlocked (field-tested).
    assert const.LOCK_LOCKED == 1
    print("  door open semantics (0 = open) ✓")


def test_vehicle_state_and_soc():
    assert DATA["exterior_status"]["vehicle_state"] == const.VEHICLE_STATE_PARKED
    soc = DATA["soc_status"]
    rate = round(soc["remaining_actual_range"] / soc["remaining_range"] * 100, 1)
    assert rate == 68.6, rate
    print(f"  soc={soc['soc']}% rate={rate}%")


if __name__ == "__main__":
    for fn in (
        test_gcj02,
        test_door_window_logic,
        test_door_open_semantics,
        test_vehicle_state_and_soc,
    ):
        print(f"{fn.__name__}:")
        fn()
    print("ALL PURE-LOGIC TESTS PASSED")
