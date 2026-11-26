import base64
import json
import time
import zlib

import pandas as pd

import yahoo_provider


class _CacheDatabase:
    def __init__(self):
        self.payload = None

    def save_market_data_cache(self, cache_key, symbol, period, interval, validate_hourly, payload, updated_at):
        self.payload = payload


def test_yahoo_cache_payload_has_json_null_for_missing_values():
    db = _CacheDatabase()
    provider = yahoo_provider.YahooProvider(database=db)
    frame = pd.DataFrame(
        {
            "open": [100.0, float("nan")],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
        },
        index=pd.DatetimeIndex(
            ["2026-09-22 10:00:00+05:30", "2026-09-22 11:00:00+05:30"]
        ),
    )

    provider._store(("RELIANCE.NS", "1d", "1m", False), frame)

    assert db.payload.startswith(yahoo_provider.CACHE_PAYLOAD_PREFIX)
    decoded = json.loads(zlib.decompress(base64.b64decode(db.payload[len(yahoo_provider.CACHE_PAYLOAD_PREFIX):])).decode())
    assert decoded["data"][1][0] is None
    assert "NaN" not in db.payload



def test_turso_cache_read_failure_falls_back_without_aborting_provider():
    class BrokenCacheDatabase:
        def load_market_data_cache(self, cache_key):
            raise RuntimeError("SQLITE_BUSY: stream was idle for too long")

        def save_market_data_cache(self, *args, **kwargs):
            raise RuntimeError("SQLITE_BUSY: stream was idle for too long")

    provider = yahoo_provider.YahooProvider(database=BrokenCacheDatabase())
    key = ("BTC-USD", "1d", "1h", False)
    assert provider._restore_persisted(key) is None


def test_turso_cache_write_failure_keeps_successful_frame_in_memory():
    class BrokenCacheDatabase:
        def save_market_data_cache(self, *args, **kwargs):
            raise RuntimeError("SQLITE_BUSY: stream was idle for too long")

    provider = yahoo_provider.YahooProvider(database=BrokenCacheDatabase())
    frame = pd.DataFrame(
        {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5]},
        index=pd.DatetimeIndex(["2026-09-22 10:00:00+05:30"]),
    )

    stored = provider._store(("BTC-USD", "1d", "1h", False), frame)
    pd.testing.assert_frame_equal(stored, frame)
    pd.testing.assert_frame_equal(provider._cached(("BTC-USD", "1d", "1h", False)), frame)



def test_compressed_persisted_cache_restores_and_legacy_json_remains_readable():
    class CacheDatabase:
        def __init__(self, payload):
            self.payload = payload

        def load_market_data_cache(self, cache_key):
            return {
                "payload": self.payload,
                "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
            }

    frame = pd.DataFrame(
        {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5]},
        index=pd.DatetimeIndex(["2026-09-22 10:00:00+05:30"]),
    )
    frame.index = frame.index.tz_convert("Asia/Kolkata")
    raw = json.dumps({
        "columns": list(frame.columns),
        "index": [x.isoformat() for x in frame.index],
        "data": frame.values.tolist(),
    }, separators=(",", ":"))
    compressed = yahoo_provider.CACHE_PAYLOAD_PREFIX + base64.b64encode(
        zlib.compress(raw.encode("utf-8"))
    ).decode("ascii")

    for payload in (compressed, raw):
        provider = yahoo_provider.YahooProvider(database=CacheDatabase(payload))
        restored = provider._restore_persisted(("RELIANCE.NS", "1d", "1h", False))
        assert restored is not None
        pd.testing.assert_frame_equal(restored[0], frame)


def test_provider_wide_backoff_survives_provider_recreation():
    class ConfigDatabase:
        def __init__(self):
            self.values = {}

        def load_app_config(self, key):
            return self.values.get(key)

        def save_app_config(self, key, payload):
            self.values[key] = payload

    db = ConfigDatabase()
    first = yahoo_provider.YahooProvider(database=db)
    delay = first._activate_backoff("GC=F", "rate_limit", provider_wide=True)
    assert delay > 0
    assert db.values[yahoo_provider.YAHOO_BACKOFF_CONFIG_KEY]["until_epoch"] > time.time()

    replacement = yahoo_provider.YahooProvider(database=db)
    assert replacement.in_backoff("RELIANCE.NS")
    assert replacement._in_backoff("RELIANCE.NS") > 0



def test_stale_compatible_cache_is_trimmed_to_requested_lookback():
    provider = yahoo_provider.YahooProvider()
    now = pd.Timestamp.now(tz="UTC")
    index = pd.DatetimeIndex(
        [now - pd.Timedelta(days=45), now - pd.Timedelta(days=20), now - pd.Timedelta(days=2)]
    ).tz_convert("Asia/Kolkata")
    frame = pd.DataFrame(
        {"open": [1.0, 2.0, 3.0], "high": [1.0, 2.0, 3.0],
         "low": [1.0, 2.0, 3.0], "close": [1.0, 2.0, 3.0]},
        index=index,
    )
    provider._last_success[("BTC-USD", "60d", "1h", False)] = (frame, time.monotonic())

    result = provider._compatible_stale(("BTC-USD", "30d", "1h", False))

    assert result is not None
    assert len(result) == 2
    assert result.index.min().tz_convert("UTC") >= yahoo_provider.YahooProvider._period_start("30d")


def test_stale_compatible_cache_rejects_insufficient_lookback():
    provider = yahoo_provider.YahooProvider()
    now = pd.Timestamp.now(tz="UTC")
    index = pd.DatetimeIndex(
        [now - pd.Timedelta(days=20), now - pd.Timedelta(days=2)]
    ).tz_convert("Asia/Kolkata")
    frame = pd.DataFrame(
        {"open": [1.0, 2.0], "high": [1.0, 2.0],
         "low": [1.0, 2.0], "close": [1.0, 2.0]},
        index=index,
    )
    provider._last_success[("BTC-USD", "20d", "1h", False)] = (frame, time.monotonic())

    assert provider._compatible_stale(("BTC-USD", "30d", "1h", False)) is None


def test_logged_yahoo_rate_limit_empty_frame_triggers_provider_wide_backoff(monkeypatch):
    import logging
    import pytest

    class FakeYFinance:
        @staticmethod
        def download(symbol, **kwargs):
            logging.getLogger("yfinance").warning(
                "YFRateLimitError: Too Many Requests"
            )
            return pd.DataFrame()

    monkeypatch.setattr(yahoo_provider, "yf", FakeYFinance())
    monkeypatch.setattr(
        yahoo_provider.GLOBAL_YAHOO_COORDINATOR, "run",
        lambda operation, priority=5: operation(),
    )
    activated = []
    monkeypatch.setattr(
        yahoo_provider.YahooProvider, "_activate_backoff",
        lambda self, symbol, reason, *, provider_wide=False:
            activated.append((symbol, reason, provider_wide)),
    )

    with pytest.raises(yahoo_provider.YahooDataError, match="no data"):
        yahoo_provider.YahooProvider().fetch(
            "GC=F", period="5d", interval="1h"
        )

    assert activated == [
        ("GC=F", "logged_rate_limit_empty_response", True)
    ]
