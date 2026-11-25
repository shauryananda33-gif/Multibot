import bandwidth_metrics


def test_bandwidth_metrics_tracks_components_without_mutating_snapshot():
    bandwidth_metrics.record(
        "unit_test",
        requests=2,
        outbound_bytes=12,
        inbound_bytes=34,
        estimated_inbound_bytes=56,
    )

    current = bandwidth_metrics.snapshot()["unit_test"]
    assert current["requests"] == 2
    assert current["outbound_bytes"] == 12
    assert current["inbound_bytes"] == 34
    assert current["estimated_inbound_bytes"] == 56

    current["requests"] = 999
    assert bandwidth_metrics.snapshot()["unit_test"]["requests"] == 2


def test_bandwidth_metrics_flush_is_safe_when_empty():
    assert bandwidth_metrics.flush(force=True) is False


def test_supabase_payload_estimates_cover_common_values():
    from supabase_db import _estimated_row_bytes, _estimated_value_bytes

    assert _estimated_value_bytes("abc") == 3
    assert _estimated_value_bytes(b"abcd") == 4
    assert _estimated_value_bytes(None) == 1
    assert _estimated_row_bytes(("abc", 123, None)) == 7
