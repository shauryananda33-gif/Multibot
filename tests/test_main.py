import io
import json

import main


def _call(method, path, *, origin=None, host="localhost:3000", forwarded=None, body=b""):
    """Drive the real WSGI app with a crafted request."""
    app = main.build_app()
    env = {
        "PATH_INFO": path, "REQUEST_METHOD": method, "HTTP_HOST": host,
        "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(), "wsgi.url_scheme": "http",
        "SERVER_NAME": "localhost", "SERVER_PORT": "3000",
    }
    if origin is not None:
        env["HTTP_ORIGIN"] = origin
    if forwarded is not None:
        env["HTTP_X_FORWARDED_HOST"] = forwarded
    captured = {}
    chunks = app(env, lambda status, headers: captured.__setitem__("status", status))
    raw = b"".join(chunks)
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        payload = None
    return captured["status"], payload


def _call_dashboard_with_headers(if_none_match=None):
    app = main.build_app()
    env = {
        "PATH_INFO": "/api/dashboard", "REQUEST_METHOD": "GET",
        "HTTP_HOST": "localhost:3000", "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(),
        "wsgi.url_scheme": "http", "SERVER_NAME": "localhost",
        "SERVER_PORT": "3000",
    }
    if if_none_match is not None:
        env["HTTP_IF_NONE_MATCH"] = if_none_match
    captured = {}
    chunks = app(env, lambda status, headers: captured.update(status=status, headers=dict(headers)))
    return captured["status"], captured["headers"], b"".join(chunks)


def test_dashboard_snapshot_supports_conditional_requests(monkeypatch):
    payload = {"ok": True, "generated_at": "2026-11-26T10:00:00+05:30", "signals": []}
    monkeypatch.setattr(main, "snapshot", lambda: payload)
    status, headers, body = _call_dashboard_with_headers()
    assert status == "200 OK"
    assert headers["ETag"].startswith('"') and headers["ETag"].endswith('"')
    assert json.loads(body) == payload
    assert int(headers["Content-Length"]) == len(body)

    not_modified, cached_headers, cached_body = _call_dashboard_with_headers(headers["ETag"])
    assert not_modified == "304 Not Modified"
    assert cached_headers["ETag"] == headers["ETag"]
    assert "Content-Length" not in cached_headers
    assert cached_body == b""


def test_registry_is_strategy_driven():
    main.ensure_runtime()
    assert set(main.REGISTRY.ids()) == {"adaptive_trend", "sweep_v2", "engulfing_66_sma"}


def test_ping_contract_exists():
    assert callable(main.web_server) and callable(main.run_strategy_cycle)


# --- configuration endpoint protection ----------------------------------

def test_dashboard_read_apis_are_public_and_configuration_is_read_only():
    for path in ("/api/dashboard", "/api/diagnostics/sweep", "/api/calendar",
                 "/api/news", "/api/settings", "/api/notifications"):
        status, payload = _call("GET", path)
        assert status == "200 OK", (path, status, payload)
        assert payload is not None
    for path in ("/api/settings", "/api/notifications"):
        status, payload = _call("POST", path, body=b"{}")
        assert status == "403 Forbidden", (path, status, payload)
        assert "disabled" in payload["error"].lower()


def test_public_dashboard_apis_reject_cross_origin_requests():
    for path in ("/api/dashboard", "/api/calendar", "/api/news",
                 "/api/settings", "/api/notifications"):
        status, payload = _call("GET", path, origin="https://evil.example")
        assert status == "403 Forbidden", (path, status, payload)
        assert payload["code"] == "CROSS_ORIGIN"


# --- scan error alert dedup ----------------------------------------------

class _FakeNotifier:
    def __init__(self):
        self.calls = []

    def deliver(self, **kwargs):
        self.calls.append(kwargs)
        return True


def test_repeated_scan_error_alerts_are_deduplicated(monkeypatch, tmp_path):
    """One asset outage must not post one ERROR bubble per sweep, while a new
    failure set and a recovered-then-failed cycle still alert.

    Suppression state is the persisted incident in db.scan_error_alerts — not
    process memory — so the same guarantees hold across a restart (covered in
    test_sweep_market_data_errors.py)."""
    from types import SimpleNamespace
    from db import DatabaseManager

    notifier = _FakeNotifier()
    monkeypatch.setattr(main, "SERVICE", SimpleNamespace(notifier=notifier))
    monkeypatch.setattr(main, "DB", DatabaseManager(str(tmp_path / "state.db")))
    payload = {"errors": 1, "checked": 25, "sent": 0}
    first = [SimpleNamespace(symbol="BTC-USD", reason="MARKET_DATA_ERROR: HTTP 429")]
    main._notify_scan("r1", "sweep_v2", payload, first)
    assert len(notifier.calls) == 1 and notifier.calls[0]["kind"] == "ERROR"
    # Same failing asset, different error text: still one incident.
    repeat = [SimpleNamespace(symbol="BTC-USD", reason="MARKET_DATA_ERROR: timeout")]
    main._notify_scan("r2", "sweep_v2", payload, repeat)
    assert len(notifier.calls) == 1
    # A different failing asset is a new incident and alerts immediately.
    widened = repeat + [SimpleNamespace(symbol="GC=F", reason="MARKET_DATA_ERROR: timeout")]
    main._notify_scan("r3", "sweep_v2", payload, widened)
    assert len(notifier.calls) == 2
    # A clean scan clears the durable incident...
    main._notify_scan("r4", "sweep_v2", {"errors": 0, "checked": 25, "sent": 1}, [])
    assert len(notifier.calls) == 3 and notifier.calls[-1]["kind"] == "SCAN"
    assert main.DB.load_scan_error_alert("sweep_v2") is None
    # ...so the next failure alerts again.
    main._notify_scan("r5", "sweep_v2", payload, first)
    assert len(notifier.calls) == 4 and notifier.calls[-1]["kind"] == "ERROR"


def test_scan_error_alert_is_bounded_by_a_repeat_window():
    """An all-day outage re-alerts at most once per hour, not per sweep.

    The window is judged from the persisted incident with wall-clock time, so a
    process restart cannot reset it (the old monotonic in-memory state could)."""
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    strategy_id, fingerprint = "adaptive_trend", "MARKET_DATA_ERROR@BTC-USD"
    assert main.scan_error_alert_decision(None, fingerprint, now=base) == "send"
    entry = {
        "strategy_id": strategy_id,
        "fingerprint": fingerprint,
        "first_sent_at": base.isoformat(),
        "last_sent_at": base.isoformat(),
        "suppressed": 0,
    }
    for _ in range(50):
        assert main.scan_error_alert_decision(entry, fingerprint, now=base) == "suppress"
    after = base + timedelta(seconds=main.SCAN_ERROR_REPEAT_SECONDS)
    assert main.scan_error_alert_decision(entry, fingerprint, now=after) == "reminder"
    # The reminder re-arms the window: bounded to one send per repeat window.
    rearmed = dict(entry, last_sent_at=after.isoformat())
    assert main.scan_error_alert_decision(rearmed, fingerprint, now=after) == "suppress"


def test_origin_check_honours_forwarded_host_behind_a_proxy():
    status, payload = _call("POST", "/api/settings", origin="https://app.example",
                            host="internal:8080", forwarded="app.example", body=b"{}")
    assert status == "403 Forbidden" and "disabled" in payload["error"].lower()
    status, payload = _call("POST", "/api/settings", origin="https://app.example",
                            host="internal:8080", body=b"{}")
    assert status == "403 Forbidden" and payload["code"] == "CROSS_ORIGIN"

def test_initial_scan_history_failure_prevents_live_scan(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from db import DatabaseError

    calls = []
    class BrokenDatabase:
        def record_scan_run(self, *args, **kwargs):
            raise DatabaseError("Turso record scan run failed: SQLITE_BUSY")

    monkeypatch.setattr(main, "_require_runtime_leader", lambda: None)
    monkeypatch.setattr(main, "ensure_runtime", lambda: None)
    monkeypatch.setattr(main, "DB", BrokenDatabase())
    monkeypatch.setattr(main, "SERVICE", SimpleNamespace(
        scan_and_dispatch=lambda *args, **kwargs: calls.append("scan") or []
    ))

    with pytest.raises(DatabaseError, match="SQLITE_BUSY"):
        main.run_strategy_cycle(
            "sweep_v2",
            now_at=main.pd.Timestamp("2026-11-23 10:00:00+05:30"),
        )
    assert calls == []


def test_final_scan_history_failure_does_not_replay_completed_scan(monkeypatch):
    from types import SimpleNamespace
    from db import DatabaseError

    class FinalWriteFailsDatabase:
        def __init__(self):
            self.writes = 0

        def record_scan_run(self, *args, **kwargs):
            self.writes += 1
            if self.writes == 2:
                raise DatabaseError("Turso final scan history failed: SQLITE_BUSY")

    scan_calls = []
    database = FinalWriteFailsDatabase()
    monkeypatch.setattr(main, "_require_runtime_leader", lambda: None)
    monkeypatch.setattr(main, "ensure_runtime", lambda: None)
    monkeypatch.setattr(main, "DB", database)
    monkeypatch.setattr(main, "SERVICE", SimpleNamespace(
        scan_and_dispatch=lambda *args, **kwargs: scan_calls.append("scan") or []
    ))
    monkeypatch.setattr(main, "LAST_SCANS", {"sweep_v2": {}})
    monkeypatch.setattr(main, "_notify_scan", lambda *args, **kwargs: None)

    result = main.run_strategy_cycle(
        "sweep_v2",
        now_at=main.pd.Timestamp("2026-11-23 10:00:00+05:30"),
    )

    assert result == []
    assert scan_calls == ["scan"]
    assert database.writes == 2
    assert main.LAST_SCANS["sweep_v2"]["status"] == "OK"


def test_standby_process_cannot_run_upstream_diagnostic_endpoints(monkeypatch):
    monkeypatch.setattr(main, "RUNTIME_LEASE_REQUIRED", True)
    monkeypatch.setattr(main, "RUNTIME_LEADER", False)
    monkeypatch.setattr(main, "RUNTIME_OWNER_ID", None)
    monkeypatch.setattr(main, "ensure_runtime", lambda: None)
    class _Registry:
        @staticmethod
        def ids():
            return ["sweep_v2"]
    monkeypatch.setattr(main, "REGISTRY", _Registry())

    for path in ("/api/diagnostics/sweep", "/api/calendar", "/api/news", "/api/backtest"):
        status, payload = _call("GET", path)
        assert status == "503 Service Unavailable", (path, status, payload)
        assert "not the active" in payload["error"]


def test_manual_and_scheduled_scan_cycles_are_serialized(monkeypatch):
    import threading
    import time
    from types import SimpleNamespace

    monkeypatch.setattr(main, "_require_runtime_leader", lambda: None)
    monkeypatch.setattr(main, "ensure_runtime", lambda: None)
    monkeypatch.setattr(
        main, "REGISTRY",
        SimpleNamespace(all=lambda: [SimpleNamespace(manifest=SimpleNamespace(id="probe"))]),
    )
    monkeypatch.setattr(main, "SCHEDULER", SimpleNamespace(is_due=lambda *args: True))
    barrier = threading.Barrier(3)
    state = {"active": 0, "maximum": 0}
    state_lock = threading.Lock()

    def fake_cycle(*args, **kwargs):
        with state_lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        time.sleep(0.05)
        with state_lock:
            state["active"] -= 1
        return ["done"]

    monkeypatch.setattr(main, "run_strategy_cycle", fake_cycle)

    def run():
        barrier.wait()
        main.run_all_cycles(force=True)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert state["maximum"] == 1


def test_dashboard_reports_the_actual_supabase_database_backend(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(main, "DB", SimpleNamespace(supabase_enabled=True, turso_enabled=True))
    assert main._database_backend_label() == "SUPABASE_POSTGRES"

    monkeypatch.setattr(main, "DB", SimpleNamespace(supabase_enabled=False, turso_enabled=False))
    assert main._database_backend_label() == "LOCAL_SQLITE"


def test_dashboard_etag_ignores_generated_at_and_supports_gzip(monkeypatch):
    import gzip

    first_payload = {"ok": True, "generated_at": "2026-11-26T10:00:00+05:30", "signals": [{"id": i} for i in range(40)]}
    second_payload = {"ok": True, "generated_at": "2026-11-26T10:05:00+05:30", "signals": [{"id": i} for i in range(40)]}
    monkeypatch.setattr(main, "snapshot", lambda: first_payload)
    status, headers, _ = _call_dashboard_with_headers()
    assert status == "200 OK"

    monkeypatch.setattr(main, "snapshot", lambda: second_payload)
    not_modified, _, cached_body = _call_dashboard_with_headers(headers["ETag"])
    assert not_modified == "304 Not Modified"
    assert cached_body == b""

    app = main.build_app()
    captured = {}
    body = b"".join(app({
        "PATH_INFO": "/api/dashboard", "REQUEST_METHOD": "GET",
        "HTTP_HOST": "localhost:3000", "HTTP_ACCEPT_ENCODING": "gzip, deflate",
        "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
    }, lambda s, h: captured.update(status=s, headers=dict(h))))
    assert captured["status"] == "200 OK"
    assert captured["headers"].get("Content-Encoding") == "gzip"
    assert json.loads(gzip.decompress(body)) == second_payload


def test_scan_error_entries_formats_market_data_error():
    from types import SimpleNamespace
    sig = SimpleNamespace(metadata={"diagnostics": {"error": "Yahoo returned no data for RELIANCE.NS"}})
    result = SimpleNamespace(symbol="RELIANCE", reason="MARKET_DATA_ERROR: no data", signal=sig)
    entries = main._scan_error_entries([result])
    assert len(entries) == 1
    assert entries[0]["heading"] == "MARKET DATA ERROR"
    assert entries[0]["reason"] == "no market data"
