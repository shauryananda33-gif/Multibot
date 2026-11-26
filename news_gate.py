"""Asset-aware optional economic-news gate."""
from __future__ import annotations

import re
import pandas as pd


class NewsGate:
    def __init__(self, news_service, enabled=False, window_minutes=30):
        self.news_service = news_service
        self.enabled = enabled
        self.window_minutes = int(window_minutes)

    @staticmethod
    def currencies_for(asset):
        """Resolve event currencies from the canonical live asset definition."""
        market = str(getattr(asset, "market", "") or "").strip().lower()
        symbol = str(getattr(asset, "symbol", "") or "").strip().upper()
        if market == "nse":
            return {"INR"}
        if market in {"gold", "crypto"}:
            return {"USD"}
        if market == "forex":
            match = re.match(r"^([A-Z]{3})([A-Z]{3})=X$", symbol)
            if match:
                return {match.group(1), match.group(2)}
            currency = str(getattr(asset, "currency", "") or "").upper()
            return {currency} if currency else set()
        currency = str(getattr(asset, "currency", "") or "").upper()
        return {currency} if currency else set()

    def check(self, asset, now):
        if not self.enabled:
            return None
        current = pd.Timestamp(now)
        payload = self.news_service.get(
            target_date=current.date().isoformat(), impacts={"High"}
        )
        currencies = self.currencies_for(asset)
        for event in payload.get("items", []):
            if currencies and str(event.get("currency", "")).upper() not in currencies:
                continue
            when = pd.Timestamp(event["datetime"])
            if when.tzinfo is None:
                when = when.tz_localize(current.tz)
            if abs((current - when.tz_convert(current.tz)).total_seconds()) <= self.window_minutes * 60:
                return {"status": "PAUSED_BY_NEWS", "event": event}
        return None
