import bandwidth_metrics


def test_bandwidth_metrics_tracks_components_without_mutating_snapshot():
    bandwidth_metrics.record(
        "unit_test",
        requests=2,
        outbound_bytes=12,
        inbound_bytes=34,
        estimated_inbound_bytes=56,
        cache_hits=3,
        cache_misses=2,
        queue_admissions=4,
        queue_timeouts=1,
        queue_wait_ms=125,
    )

    current = bandwidth_metrics.snapshot()["unit_test"]
    assert current["requests"] == 2
    assert current["outbound_bytes"] == 12
    assert current["inbound_bytes"] == 34
    assert current["estimated_inbound_bytes"] == 56
    assert current["cache_hits"] == 3
    assert current["cache_misses"] == 2
    assert current["queue_admissions"] == 4
    assert current["queue_timeouts"] == 1
    assert current["queue_wait_ms"] == 125

    current["requests"] = 999
    assert bandwidth_metrics.snapshot()["unit_test"]["requests"] == 2
    assert bandwidth_metrics.flush(force=True) is True


def test_bandwidth_metrics_flush_is_safe_when_empty():
    assert bandwidth_metrics.flush(force=True) is False
