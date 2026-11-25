import pandas as pd
import pytest

import yahoo_provider


def _fake_download(*args, **kwargs):
    index = pd.DatetimeIndex(
        ["2026-09-22 10:00:00", "2026-09-22 11:00:00"],
        tz="UTC",
    )
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "RELIANCE.NS"),
            ("Open", "duplicate"),
            ("High", "RELIANCE.NS"),
            ("Low", "RELIANCE.NS"),
            ("Close", "RELIANCE.NS"),
        ]
    )
    return pd.DataFrame(
        [
            [100.0, 100.0, 101.0, 99.0, 100.5],
            [101.0, 101.0, 102.0, 100.0, 101.5],
        ],
        index=index,
        columns=columns,
    )


def test_yahoo_provider_flattens_duplicate_ohlc_labels(monkeypatch):
    monkeypatch.setattr(yahoo_provider.yf, "download", _fake_download)
    provider = yahoo_provider.YahooProvider()

    frame = provider.fetch(
        "RELIANCE.NS",
        period="1d",
        interval="1m",
        validate_hourly=False,
    )

    assert list(frame.columns) == ["open", "high", "low", "close"]
    assert frame["close"].iloc[-1] == pytest.approx(101.5)
    assert not frame.columns.duplicated().any()


def test_yahoo_provider_rejects_duplicate_timestamps(monkeypatch):
    def fake_download(*args, **kwargs):
        index = pd.DatetimeIndex(
            ["2026-09-22 10:00:00", "2026-09-22 10:00:00"],
            tz="UTC",
        )
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [101.0, 102.0],
                "Low": [99.0, 100.0],
                "Close": [100.5, 101.5],
            },
            index=index,
        )

    monkeypatch.setattr(yahoo_provider.yf, "download", fake_download)
    provider = yahoo_provider.YahooProvider()

    with pytest.raises(
        yahoo_provider.YahooDataError,
        match="duplicate candle timestamps",
    ):
        provider.fetch(
            "RELIANCE.NS",
            period="1d",
            interval="1m",
            validate_hourly=False,
        )


def test_yahoo_rate_limit_backoff_is_shared_across_symbols(monkeypatch):
    calls = []

    def rate_limited_download(symbol, **kwargs):
        calls.append(symbol)
        raise RuntimeError("YFRateLimitError: Too Many Requests")

    monkeypatch.setattr(yahoo_provider.yf, "download", rate_limited_download)
    provider = yahoo_provider.YahooProvider()

    with pytest.raises(yahoo_provider.YahooDataError, match="request failed"):
        provider.fetch("GC=F", period="5d", interval="1h")

    with pytest.raises(yahoo_provider.YahooDataError, match="rate-limit backoff"):
        provider.fetch("USDJPY=X", period="5d", interval="1h")

    assert calls == ["GC=F"]


def test_yahoo_empty_response_only_backs_off_the_affected_symbol(monkeypatch):
    calls = []

    def empty_then_valid_download(symbol, **kwargs):
        calls.append(symbol)
        if symbol == "GC=F":
            return pd.DataFrame()
        return _fake_download(symbol, **kwargs)

    monkeypatch.setattr(yahoo_provider.yf, "download", empty_then_valid_download)
    provider = yahoo_provider.YahooProvider()

    with pytest.raises(yahoo_provider.YahooDataError, match="returned no data"):
        provider.fetch("GC=F", period="5d", interval="1h")

    # A missing/unsupported Gold interval must not block unrelated symbols.
    frame = provider.fetch("SBIN.NS", period="5d", interval="1h", validate_hourly=False)
    assert not frame.empty
    assert calls == ["GC=F", "SBIN.NS"]

    # The affected symbol itself remains protected from repeated requests.
    with pytest.raises(yahoo_provider.YahooDataError, match="rate-limit backoff"):
        provider.fetch("GC=F", period="5d", interval="1h")
    assert calls == ["GC=F", "SBIN.NS"]


def test_compatible_memory_cache_reuses_larger_fresh_lookback(monkeypatch):
    calls = []

    def unexpected_download(*args, **kwargs):
        calls.append(args)
        raise AssertionError("compatible memory cache should avoid Yahoo request")

    monkeypatch.setattr(yahoo_provider.yf, "download", unexpected_download)
    provider = yahoo_provider.YahooProvider()
    now = pd.Timestamp.now(tz="UTC")
    index = pd.date_range(end=now, periods=120, freq="h")
    frame = pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
        index=index,
    )
    provider._store(("RELIANCE.NS", "5d", "1h", True), frame)

    provenance = {}
    reused = provider.fetch(
        "RELIANCE.NS",
        period="1d",
        interval="1h",
        validate_hourly=True,
        provenance=provenance,
    )

    assert not reused.empty
    assert reused.index.min() >= (now - pd.Timedelta(days=1)).tz_convert(reused.index.tz)
    assert provenance["source"] == "memory_cache_compatible"
    assert calls == []


def test_compatible_memory_cache_never_crosses_symbols_or_intervals(monkeypatch):
    calls = []

    def fake_download(symbol, **kwargs):
        calls.append((symbol, kwargs["interval"]))
        return _fake_download(symbol, **kwargs)

    monkeypatch.setattr(yahoo_provider.yf, "download", fake_download)
    provider = yahoo_provider.YahooProvider()
    now = pd.Timestamp.now(tz="UTC")
    index = pd.date_range(end=now, periods=120, freq="h")
    frame = pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
        index=index,
    )
    provider._store(("RELIANCE.NS", "5d", "1h", False), frame)

    provider.fetch("SBIN.NS", period="1d", interval="1h", validate_hourly=False)
    provider.fetch("RELIANCE.NS", period="1d", interval="30m", validate_hourly=False)

    assert calls == [("SBIN.NS", "1h"), ("RELIANCE.NS", "30m")]
