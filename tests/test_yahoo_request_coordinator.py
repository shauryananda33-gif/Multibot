from yahoo_request_coordinator import YahooRequestCoordinator

def test_coordinator_runs_callbacks_with_zero_spacing():
    coordinator = YahooRequestCoordinator(min_interval_seconds=0, queue_timeout_seconds=1)
    assert coordinator.run(lambda: "first") == "first"
    assert coordinator.run(lambda: "second") == "second"

def test_coordinator_prioritizes_waiting_requests():
    import threading
    import time
    coordinator = YahooRequestCoordinator(min_interval_seconds=0, queue_timeout_seconds=2)
    entered = threading.Event()
    release = threading.Event()
    order = []
    def first():
        entered.set()
        release.wait(1)
        order.append("active")
    worker = threading.Thread(target=lambda: coordinator.run(first, priority=5))
    worker.start()
    assert entered.wait(1)
    low = threading.Thread(target=lambda: coordinator.run(lambda: order.append("low"), priority=10))
    high = threading.Thread(target=lambda: coordinator.run(lambda: order.append("high"), priority=0))
    low.start()
    time.sleep(0.02)
    high.start()
    time.sleep(0.02)
    release.set()
    for thread in (worker, low, high):
        thread.join(2)
        assert not thread.is_alive()
    assert order == ["active", "high", "low"]

def test_queue_timeout_removes_ticket_and_recovers():
    import threading
    import pytest
    coordinator = YahooRequestCoordinator(min_interval_seconds=0, queue_timeout_seconds=0.05)
    entered = threading.Event()
    release = threading.Event()
    worker = threading.Thread(target=lambda: coordinator.run(lambda: (entered.set(), release.wait(1)), priority=0))
    worker.start()
    assert entered.wait(1)
    with pytest.raises(TimeoutError, match="admission queue timed out"):
        coordinator.run(lambda: None, priority=5)
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert coordinator.run(lambda: "recovered") == "recovered"



def test_coordinator_records_admission_metrics():
    import bandwidth_metrics
    coordinator = YahooRequestCoordinator(min_interval_seconds=0, queue_timeout_seconds=1)
    before = bandwidth_metrics.snapshot().get("yahoo_queue", {}).get("queue_admissions", 0)
    assert coordinator.run(lambda: "ok") == "ok"
    after = bandwidth_metrics.snapshot()["yahoo_queue"]["queue_admissions"]
    assert after == before + 1
