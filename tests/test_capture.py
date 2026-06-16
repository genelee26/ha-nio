"""HA-free tests for capture.py: URL parsing, app_ver extraction, and the
v1->v2 query reconstruction used by the config-entry migration.

Run directly: python tests/test_capture.py
"""

import sys
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "nio"
sys.path.insert(0, str(COMPONENT))

import capture  # noqa: E402
import const  # noqa: E402

# A realistic capture (the 6.6.0 app: includes field=key, app_ver=6.6.0).
FULL_URL = (
    "https://icar.nio.com/api/2/rvs/vehicle/600c25b2a1f848361823830770001010/status"
    "?field=power_swap_order&field=key&field=soc&timestamp=1781593788"
    "&app_ver=6.6.0&lang=zh-CN&app_id=10002&region=cn"
    "&device_id=af81b84edf724951a7ff67d97fa6b15d&sign=016af3608d5594a155253c8773c585f7"
)


def test_parse_full_url():
    vid, query = capture.parse_capture(FULL_URL)
    assert vid == "600c25b2a1f848361823830770001010", vid
    # query is everything after '?', byte-for-byte (no re-encoding, no host).
    assert query == FULL_URL.split("?", 1)[1], query
    assert query.startswith("field=power_swap_order")
    assert query.endswith("sign=016af3608d5594a155253c8773c585f7")
    print(f"  full url -> vid={vid[:8]}… query[{len(query)}B] ✓")


def test_parse_path_only_and_quotes():
    # Just the path+query (no scheme/host), wrapped in quotes + whitespace.
    raw = "  '/api/2/rvs/vehicle/ABC123/status?field=soc&timestamp=1&sign=x'  "
    vid, query = capture.parse_capture(raw)
    assert vid == "ABC123", vid
    assert query == "field=soc&timestamp=1&sign=x", query
    print("  path-only + quotes/whitespace ✓")


def test_parse_drops_fragment():
    vid, query = capture.parse_capture(
        "/api/2/rvs/vehicle/V/status?timestamp=1&sign=x#frag"
    )
    assert query == "timestamp=1&sign=x", query
    print("  fragment dropped ✓")


def test_parse_request_line_and_multiline():
    # Whole proxy "request line": method + URL + protocol on one line.
    vid, query = capture.parse_capture(
        "GET https://icar.nio.com/api/2/rvs/vehicle/V1/status?timestamp=1&sign=x HTTP/2"
    )
    assert vid == "V1", vid
    assert query == "timestamp=1&sign=x", query  # " HTTP/2" trimmed off

    # URL followed by header lines (pasted blob) — keep only the query.
    blob = (
        "/api/2/rvs/vehicle/V2/status?field=soc&timestamp=2&sign=y\n"
        "Host: tsp.nio.com\n"
        "Authorization: Bearer abc\n"
    )
    vid, query = capture.parse_capture(blob)
    assert vid == "V2", vid
    assert query == "field=soc&timestamp=2&sign=y", query  # newline + headers trimmed
    print("  request-line + multiline blob trimmed to query ✓")


def test_parse_rejects_bad_input():
    bad = [
        "",
        "not a url",
        "https://app.nio.com/c/award_cn/checkin?app_id=10086",  # no /vehicle/<id>/status
        "/api/2/rvs/vehicle/V/status",  # no query
        "/api/2/rvs/vehicle/V/status?field=soc&app_id=10002",  # no sign/timestamp
    ]
    for raw in bad:
        try:
            capture.parse_capture(raw)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {raw!r}")
    print("  rejects empty / non-status / unsigned / query-less ✓")


def test_app_ver_from_query():
    assert capture.app_ver_from_query("field=soc&app_ver=6.6.0&sign=x") == "6.6.0"
    assert capture.app_ver_from_query("app_ver=6.3.0") == "6.3.0"
    assert capture.app_ver_from_query("field=soc&sign=x") is None
    # must not match a substring of another key
    assert capture.app_ver_from_query("xapp_ver=9&app_ver=1.2") == "1.2"
    print("  app_ver extraction ✓")


def test_reconstruct_query_v1_matches_old_client():
    # The legacy v1 client built params in exactly this order; the reconstructed
    # string must reproduce it byte-for-byte so the old sign still validates.
    old = {
        const.CONF_DEVICE_ID: "DEV",
        const.CONF_SIGN: "SIG",
        const.CONF_TIMESTAMP: "12345",
        const.CONF_APP_VER: "6.3.0",
        const.CONF_REGION: "cn",
    }
    query = capture.reconstruct_query_v1(old)

    expected_parts = [f"field={f}" for f in const.API_FIELDS]
    expected_parts += [
        "app_ver=6.3.0",
        "region=cn",
        f"app_id={const.API_APP_ID}",
        "device_id=DEV",
        "lang=zh-CN",
        "timestamp=12345",
        "sign=SIG",
    ]
    assert query == "&".join(expected_parts), query

    # Round-trips through parse_capture (it's a valid signed status query).
    vid, q2 = capture.parse_capture(f"/api/2/rvs/vehicle/V/status?{query}")
    assert q2 == query
    assert capture.app_ver_from_query(query) == "6.3.0"
    print(f"  v1 reconstruction byte-exact ({len(query)}B) ✓")


def test_reconstruct_defaults_when_missing():
    # app_ver/region may be absent on very old entries -> fall back to defaults.
    old = {
        const.CONF_DEVICE_ID: "DEV",
        const.CONF_SIGN: "SIG",
        const.CONF_TIMESTAMP: "1",
    }
    query = capture.reconstruct_query_v1(old)
    assert f"app_ver={const.DEFAULT_APP_VER}" in query
    assert f"region={const.DEFAULT_REGION}" in query
    print("  v1 reconstruction defaults ✓")


if __name__ == "__main__":
    for fn in (
        test_parse_full_url,
        test_parse_path_only_and_quotes,
        test_parse_drops_fragment,
        test_parse_request_line_and_multiline,
        test_parse_rejects_bad_input,
        test_app_ver_from_query,
        test_reconstruct_query_v1_matches_old_client,
        test_reconstruct_defaults_when_missing,
    ):
        print(f"{fn.__name__}:")
        fn()
    print("ALL CAPTURE TESTS PASSED")
