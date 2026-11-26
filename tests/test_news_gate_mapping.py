from types import SimpleNamespace

from news_gate import NewsGate


def test_news_gate_uses_actual_asset_market_and_pair_currencies():
    cases = {
        "^NSEI": ("NSE", "INR", {"INR"}),
        "BTC-USD": ("Crypto", "USD", {"USD"}),
        "GC=F": ("Gold", "USD", {"USD"}),
        "EURUSD=X": ("Forex", "USD", {"EUR", "USD"}),
        "USDJPY=X": ("Forex", "JPY", {"USD", "JPY"}),
    }
    for symbol, (market, currency, expected) in cases.items():
        asset = SimpleNamespace(symbol=symbol, market=market, currency=currency)
        assert NewsGate.currencies_for(asset) == expected


def test_news_gate_disabled_by_default_does_not_fetch_calendar():
    class ForbiddenNews:
        def get(self, **kwargs):
            raise AssertionError("disabled news gate must not fetch calendar data")

    gate = NewsGate(ForbiddenNews())
    asset = SimpleNamespace(symbol="GC=F", market="Gold", currency="USD")
    assert gate.check(asset, "2026-11-26T10:00:00+05:30") is None


def test_custom_global_asset_falls_back_to_its_configured_currency():
    asset = SimpleNamespace(symbol="CUSTOM", market="Global", currency="USD")
    assert NewsGate.currencies_for(asset) == {"USD"}
