"""Yahoo Finance market-data adapter for MULTIBOT2.

Yahoo Finance is the locked market-data source. This provider is deliberately
rate-limit conscious: cache first, deduplicate requests per symbol, back off
exponentially after failures, and return recent valid data whenever possible.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import zlib
import warnings
from datetime import datetime, timezone
from threading import Lock, RLock
from typing import Optional

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

from candles import validate_hourly_observations
from config import IST_TIMEZONE
from yahoo_request_coordinator import GLOBAL_YAHOO_COORDINATOR, YahooRequestQueueTimeout

YF_TTL_BY_INTERVAL = {"1m": 45.0, "30m": 120.0, "1h": 300.0, "4h": 300.0, "1d": 600.0}
YAHOO_BACKOFF_SECONDS = 120.0
YAHOO_MAX_BACKOFF_SECONDS = 1800.0
YAHOO_STALE_GRACE_SECONDS = 900.0
CACHE_PAYLOAD_PREFIX = "zlib1:"
YAHOO_BACKOFF_CONFIG_KEY = "yahoo_provider_backoff_v1"


class YahooDataError(RuntimeError):
    """Raised when Yahoo data cannot be safely returned."""


logger = logging.getLogger(__name__)


class YahooProvider:
    """Rate-conscious Yahoo Finance provider with resilient caching."""

    def __init__(self, *, session: Optional[object] = None, database=None) -> None:
        self._external_session = session
        self._database = database
        self._cache: dict[tuple[str, str, str, bool], tuple[pd.DataFrame, float]] = {}
        self._last_success: dict[tuple[str, str, str, bool], tuple[pd.DataFrame, float]] = {}
        self._backoff_until: dict[str, float] = {}
        self._failure_count: dict[str, int] = {}
        # Yahoo applies throttles at provider/account level, not reliably per
        # ticker. Coordinate cooldowns across symbols after a confirmed or
        # suspected rate-limit response so concurrent strategies do not keep
        # hitting the same upstream limit with different symbols.
        self._global_backoff_until = 0.0
        self._global_failure_count = 0
        self._symbol_locks: dict[str, Lock] = {}
        self._lock = RLock()
        self._restore_provider_backoff()

    def _restore_provider_backoff(self) -> None:
        """Restore a provider-wide cooldown across process restarts.

        The active runtime lease fences market-data work to one leader. Persisting
        the cooldown lets a replacement leader inherit a Yahoo throttle instead
        of immediately repeating the request after a restart.
        """
        if self._database is None:
            return
        loader = getattr(self._database, "load_app_config", None)
        if not callable(loader):
            return
        try:
            state = loader(YAHOO_BACKOFF_CONFIG_KEY)
            if not isinstance(state, dict):
                return
            remaining = float(state.get("until_epoch", 0.0)) - time.time()
            if remaining <= 0:
                return
            with self._lock:
                self._global_backoff_until = time.monotonic() + remaining
                self._global_failure_count = max(0, int(state.get("failure_count", 0)))
            logger.info("Restored persisted Yahoo provider cooldown | retry_in=%ds", int(remaining))
        except Exception as exc:
            logger.warning("Yahoo provider cooldown restore failed; continuing with local state: %s", exc)

    def _persist_provider_backoff(self, delay: float) -> None:
        if self._database is None:
            return
        saver = getattr(self._database, "save_app_config", None)
        if not callable(saver):
            return
        try:
            saver(YAHOO_BACKOFF_CONFIG_KEY, {
                "until_epoch": time.time() + max(0.0, float(delay)),
                "failure_count": self._global_failure_count,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            # The local cooldown remains active if the durable write is unavailable.
            logger.warning("Yahoo provider cooldown persistence failed: %s", exc)

    def _clear_provider_backoff(self) -> None:
        with self._lock:
            had_backoff = self._global_failure_count > 0 or self._global_backoff_until > 0
            self._global_failure_count = 0
            self._global_backoff_until = 0.0
        if not had_backoff or self._database is None:
            return
        saver = getattr(self._database, "save_app_config", None)
        if not callable(saver):
            return
        try:
            saver(YAHOO_BACKOFF_CONFIG_KEY, {
                "until_epoch": 0.0,
                "failure_count": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            logger.warning("Yahoo provider cooldown reset persistence failed: %s", exc)

    def _ttl(self, interval: str) -> float:
        return YF_TTL_BY_INTERVAL.get(interval, 60.0)

    @staticmethod
    def _record_cache_event(*, hit: bool = False, miss: bool = False) -> None:
        try:
            from bandwidth_metrics import record as record_bandwidth
            record_bandwidth(
                "yahoo_cache",
                requests=0,
                cache_hits=int(bool(hit)),
                cache_misses=int(bool(miss)),
            )
        except Exception:
            logger.debug("Yahoo cache telemetry unavailable", exc_info=True)

    @staticmethod
    def _key_id(key: tuple[str, str, str, bool]) -> str:
        return "|".join((key[0], key[1], key[2], str(int(bool(key[3])))))

    def _symbol_lock(self, symbol: str) -> Lock:
        with self._lock:
            return self._symbol_locks.setdefault(symbol, Lock())

    def _cached(self, key: tuple[str, str, str, bool]) -> Optional[pd.DataFrame]:
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            frame, cached_at = item
            if time.monotonic() - cached_at < self._ttl(key[2]):
                return frame.copy()
            self._cache.pop(key, None)
        return None

    @staticmethod
    def _period_start(period: str, now: Optional[pd.Timestamp] = None) -> Optional[pd.Timestamp]:
        """Return a conservative start boundary for common Yahoo period values."""
        current = now or pd.Timestamp.now(tz="UTC")
        value = str(period).strip().lower()
        if value == "ytd":
            return current.normalize().replace(month=1, day=1)
        import re
        match = re.fullmatch(r"(\d+)(d|mo|y)", value)
        if not match:
            return None
        amount, unit = int(match.group(1)), match.group(2)
        days = amount if unit == "d" else amount * 30 if unit == "mo" else amount * 365
        return current - pd.Timedelta(days=days)

    def _compatible_cached(self, key: tuple[str, str, str, bool]) -> Optional[pd.DataFrame]:
        """Reuse a fresh in-memory frame only when it covers the requested window.

        Symbol, interval and validation mode must match. The returned frame is
        trimmed to the requested lookback so callers see the same history scope
        they asked Yahoo for.
        """
        start = self._period_start(key[1])
        if start is None:
            return None
        now = time.monotonic()
        candidates = []
        with self._lock:
            for other_key, (frame, saved_at) in self._cache.items():
                if other_key == key:
                    continue
                if (other_key[0], other_key[2], other_key[3]) != (key[0], key[2], key[3]):
                    continue
                if now - saved_at >= self._ttl(key[2]) or frame.empty:
                    continue
                index = frame.index
                if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
                    continue
                if index.min().tz_convert("UTC") <= start:
                    candidates.append((saved_at, frame))
        if not candidates:
            return None
        _, frame = max(candidates, key=lambda item: item[0])
        trimmed = frame.loc[frame.index.tz_convert("UTC") >= start].copy()
        if trimmed.empty:
            return None
        logger.info(
            "Yahoo compatible memory cache hit | symbol=%s requested_period=%s interval=%s",
            key[0], key[1], key[2],
        )
        return trimmed

    def _restore_persisted(self, key: tuple[str, str, str, bool]):
        if self._database is None:
            return None
        try:
            row = self._database.load_market_data_cache(self._key_id(key))
        except Exception as exc:
            # Durable cache is an optimization, not a prerequisite for a live
            # Yahoo request. A transient Turso failure must not abort the scan.
            logger.warning(
                "Yahoo persistent cache read failed | symbol=%s error=%s",
                key[0], exc,
            )
            return None
        if not row:
            logger.info("Yahoo persistent cache miss | symbol=%s key=%s", key[0], self._key_id(key))
            return None
        try:
            updated = pd.Timestamp(row["updated_at"])
            if updated.tzinfo is None:
                updated = updated.tz_localize("UTC")
            age = (datetime.now(timezone.utc) - updated.to_pydatetime().astimezone(timezone.utc)).total_seconds()
            if age > YAHOO_STALE_GRACE_SECONDS:
                return None
            stored_payload = str(row["payload"])
            from bandwidth_metrics import record as record_bandwidth
            record_bandwidth(
                "supabase_market_cache",
                requests=1,
                estimated_inbound_bytes=len(stored_payload.encode("utf-8")),
            )
            if stored_payload.startswith(CACHE_PAYLOAD_PREFIX):
                encoded = stored_payload[len(CACHE_PAYLOAD_PREFIX):]
                decoded = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
            else:
                # Read existing plain-JSON rows during the compatibility window.
                decoded = stored_payload
            payload = json.loads(decoded)
            frame = pd.DataFrame(payload["data"], columns=payload["columns"])
            frame.index = pd.to_datetime(payload["index"], utc=True).tz_convert(IST_TIMEZONE)
            logger.info("Yahoo persistent cache hit | symbol=%s age_seconds=%d", key[0], int(age))
            return frame, age
        except Exception as exc:
            logger.warning("Yahoo persistent cache restore failed | symbol=%s error=%s", key[0], exc)
            return None

    def _compatible_stale(self, key: tuple[str, str, str, bool]) -> Optional[pd.DataFrame]:
        """Return recent, same-symbol/interval stale data covering the requested window."""
        start = self._period_start(key[1])
        now = time.monotonic()
        candidates: list[tuple[pd.DataFrame, float]] = []
        with self._lock:
            exact = self._last_success.get(key)
            if exact is not None:
                candidates.append(exact)
            for other_key, item in self._last_success.items():
                if other_key == key:
                    continue
                if other_key[0] == key[0] and other_key[2] == key[2] and other_key[3] == key[3]:
                    # Unknown Yahoo period syntax cannot prove that a different
                    # cached request covers the requested history.
                    if start is not None:
                        candidates.append(item)
        fresh = [(frame, saved) for frame, saved in candidates if now - saved <= YAHOO_STALE_GRACE_SECONDS]
        compatible = []
        for frame, saved in fresh:
            if frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
                continue
            if start is None:
                if key in self._last_success:
                    compatible.append((frame, saved))
                continue
            utc_index = frame.index.tz_convert("UTC")
            if utc_index.min() > start:
                continue
            trimmed = frame.loc[utc_index >= start].copy()
            if not trimmed.empty:
                compatible.append((trimmed, saved))
        if not compatible:
            return None
        frame, _ = max(compatible, key=lambda item: item[1])
        logger.info(
            "Yahoo stale fallback | symbol=%s requested=%s compatible_cache=true",
            key[0], self._key_id(key),
        )
        return frame.copy()

    def _stale(self, key: tuple[str, str, str, bool]) -> Optional[pd.DataFrame]:
        frame = self._compatible_stale(key)
        if frame is not None:
            return frame
        persisted = self._restore_persisted(key)
        if persisted is not None:
            frame, age = persisted
            with self._lock:
                self._last_success[key] = (frame.copy(), time.monotonic() - age)
            return frame.copy()
        return None

    def _store(self, key: tuple[str, str, str, bool], frame: pd.DataFrame) -> pd.DataFrame:
        now = time.monotonic()
        with self._lock:
            self._cache[key] = (frame.copy(), now)
            self._last_success[key] = (frame.copy(), now)
            self._failure_count.pop(key[0], None)
            self._backoff_until.pop(key[0], None)
        self._clear_provider_backoff()
        if self._database is not None:
            # JSON does not permit IEEE NaN/Infinity values. Convert missing
            # numeric cells to JSON null before persisting the cache payload.
            safe_frame = frame.astype(object).where(pd.notna(frame), None)
            payload = {
                "columns": list(safe_frame.columns),
                "index": [x.isoformat() for x in safe_frame.index],
                "data": safe_frame.values.tolist(),
            }
            try:
                serialized = json.dumps(
                    payload, separators=(",", ":"), default=str, allow_nan=False
                )
                compressed = CACHE_PAYLOAD_PREFIX + base64.b64encode(
                    zlib.compress(serialized.encode("utf-8"), level=6)
                ).decode("ascii")
                from bandwidth_metrics import record as record_bandwidth
                record_bandwidth(
                    "supabase_market_cache",
                    requests=1,
                    outbound_bytes=len(compressed.encode("utf-8")),
                )
                self._database.save_market_data_cache(
                    self._key_id(key), key[0], key[1], key[2], key[3],
                    compressed,
                    datetime.now(timezone.utc).isoformat(),
                )
                logger.info("Yahoo persistent cache saved | symbol=%s key=%s", key[0], self._key_id(key))
            except Exception as exc:
                # Keep the successfully fetched frame in memory even when
                # durable persistence is temporarily unavailable.
                logger.warning(
                    "Yahoo persistent cache save failed | symbol=%s error=%s",
                    key[0], exc,
                )
        return frame.copy()

    def _activate_backoff(
        self,
        symbol: str,
        reason: str,
        *,
        provider_wide: bool = False,
    ) -> float:
        now = time.monotonic()
        with self._lock:
            failures = self._failure_count.get(symbol, 0) + 1
            self._failure_count[symbol] = failures
            delay = min(
                YAHOO_BACKOFF_SECONDS * (2 ** (failures - 1)),
                YAHOO_MAX_BACKOFF_SECONDS,
            )
            self._backoff_until[symbol] = now + delay
            if provider_wide:
                self._global_failure_count += 1
                global_delay = min(
                    YAHOO_BACKOFF_SECONDS * (2 ** (self._global_failure_count - 1)),
                    YAHOO_MAX_BACKOFF_SECONDS,
                )
                self._global_backoff_until = max(
                    self._global_backoff_until,
                    now + global_delay,
                )
            else:
                global_delay = 0.0
        logger.warning(
            "Yahoo backoff activated | symbol=%s failures=%d retry_in=%ds "
            "scope=%s reason=%s",
            symbol, failures, int(max(delay, global_delay)),
            "provider" if provider_wide else "symbol", reason,
        )
        effective_delay = max(delay, global_delay)
        if provider_wide:
            with self._lock:
                persisted_delay = max(
                    0.0, self._global_backoff_until - time.monotonic()
                )
            self._persist_provider_backoff(persisted_delay)
        return effective_delay

    @staticmethod
    def _validate_request(period: str, interval: str) -> None:
        if interval == "1m" and period not in {"1d", "2d", "5d", "7d"}:
            raise YahooDataError(
                f"Yahoo 1m data requires a short lookback (1d/2d/5d/7d); got period={period}"
            )

    def _in_backoff(self, symbol: str) -> float:
        with self._lock:
            now = time.monotonic()
            symbol_wait = self._backoff_until.get(symbol, 0.0) - now
            provider_wait = self._global_backoff_until - now
            return max(0.0, symbol_wait, provider_wait)

    @staticmethod
    def _mark_provenance(provenance: Optional[dict], *, source: str, age_seconds: Optional[float] = None, cache_key: Optional[str] = None) -> None:
        """Record where a returned frame actually came from.

        Filled into the caller's dict so the scan path can report
        fresh-vs-cache (and cache age) when a later validation failure needs
        diagnostics. Never raises: provenance is observational metadata.
        """
        if provenance is None:
            return
        provenance.update({
            "source": source,
            "age_seconds": age_seconds,
            "cache_key": cache_key,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    def fetch(
        self,
        symbol: str,
        *,
        period: str = "5d",
        interval: str = "1h",
        validate_hourly: bool = True,
        provenance: Optional[dict] = None,
        priority: int = 5,
    ) -> pd.DataFrame:
        """Fetch Yahoo candles with cache-first, deduplication and backoff."""
        if yf is None:
            raise YahooDataError("yfinance is not installed")

        self._validate_request(period, interval)
        key = (symbol, period, interval, validate_hourly)

        cached = self._cached(key)
        if cached is not None:
            self._record_cache_event(hit=True)
            self._mark_provenance(provenance, source="memory_cache", age_seconds=0.0, cache_key=self._key_id(key))
            return cached

        symbol_lock = self._symbol_lock(symbol)
        with symbol_lock:
            # Another concurrent caller may have completed while we waited.
            cached = self._cached(key)
            if cached is not None:
                self._record_cache_event(hit=True)
                self._mark_provenance(provenance, source="memory_cache", age_seconds=0.0, cache_key=self._key_id(key))
                return cached

            compatible = self._compatible_cached(key)
            if compatible is not None:
                self._record_cache_event(hit=True)
                self._mark_provenance(
                    provenance, source="memory_cache_compatible",
                    age_seconds=0.0, cache_key=self._key_id(key),
                )
                return compatible

            persisted = self._restore_persisted(key)
            if persisted is not None:
                frame, age = persisted
                if age <= self._ttl(interval):
                    self._record_cache_event(hit=True)
                    now = time.monotonic()
                    with self._lock:
                        self._cache[key] = (frame.copy(), now)
                        self._last_success[key] = (frame.copy(), now - age)
                    self._mark_provenance(provenance, source="persisted_cache", age_seconds=round(age, 1), cache_key=self._key_id(key))
                    return frame.copy()

            self._record_cache_event(miss=True)
            retry_in = self._in_backoff(symbol)
            if retry_in > 0:
                stale = self._stale(key)
                if stale is not None:
                    logger.info(
                        "Yahoo request skipped during backoff | symbol=%s retry_in=%ds source=cache",
                        symbol, int(retry_in),
                    )
                    self._mark_provenance(provenance, source="stale_fallback", cache_key=self._key_id(key))
                    return stale
                raise YahooDataError(
                    f"Yahoo Finance is in rate-limit backoff for {symbol}; retry_in={int(retry_in)}s"
                )

            # yfinance returns parsed DataFrames, not raw response bodies.
            # Count the request and report parsed-frame size as an estimate only.
            from bandwidth_metrics import record as record_bandwidth
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="The .*generic.* unit for NumPy timedelta is deprecated.*",
                        category=DeprecationWarning,
                    )
                    frame = GLOBAL_YAHOO_COORDINATOR.run(
                        lambda: yf.download(
                            symbol,
                            period=period,
                            interval=interval,
                            progress=False,
                            auto_adjust=True,
                            threads=False,
                        ),
                        priority=priority,
                    )
            except Exception as exc:
                if isinstance(exc, YahooRequestQueueTimeout):
                    stale = self._stale(key)
                    if stale is not None:
                        self._mark_provenance(provenance, source="stale_fallback", cache_key=self._key_id(key))
                        return stale
                    raise YahooDataError(
                        f"Yahoo request was not admitted before queue timeout for {symbol}"
                    ) from exc
                record_bandwidth("yahoo_finance", requests=1)
                message = str(exc)
                rate_limited = (
                    "429" in message
                    or "too many requests" in message.lower()
                    or "rate limit" in message.lower()
                    or "ratelimit" in message.lower()
                )
                self._activate_backoff(
                    symbol,
                    "rate_limit" if rate_limited else "request_error",
                    provider_wide=rate_limited,
                )
                stale = self._stale(key)
                if stale is not None:
                    self._mark_provenance(provenance, source="stale_fallback", cache_key=self._key_id(key))
                    return stale
                raise YahooDataError(f"Yahoo request failed for {symbol}: {exc}") from exc

            # Empty responses are ambiguous: Yahoo also returns them for
            # unavailable symbols/periods (for example GC=F intraday history).
            # Do not block every unrelated market on that evidence alone.
            # Confirmed HTTP/YF rate-limit exceptions above still use provider-wide
            # backoff; an empty response receives only a per-symbol cooldown.
            if frame is None or frame.empty:
                self._activate_backoff(
                    symbol,
                    "empty_response",
                    provider_wide=False,
                )
                stale = self._stale(key)
                if stale is not None:
                    self._mark_provenance(provenance, source="stale_fallback", cache_key=self._key_id(key))
                    return stale
                raise YahooDataError(f"Yahoo returned no data for {symbol}")

            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)

            # yfinance can occasionally return duplicate labels after flattening
            # a single-ticker MultiIndex response. Keep the first occurrence so
            # every OHLC field remains a scalar Series at the provider boundary.
            frame = frame.loc[:, ~frame.columns.duplicated(keep="first")]

            required = {"Open", "High", "Low", "Close"}
            if not required.issubset(frame.columns):
                raise YahooDataError(f"Yahoo response for {symbol} is missing OHLC columns")

            frame = frame[["Open", "High", "Low", "Close"]].copy()
            frame.columns = [column.lower() for column in frame.columns]

            if not isinstance(frame.index, pd.DatetimeIndex):
                raise YahooDataError("Yahoo response has no DatetimeIndex")
            if frame.index.tz is None:
                frame.index = frame.index.tz_localize("UTC")

            if frame.index.has_duplicates:
                raise YahooDataError(
                    f"Yahoo response for {symbol} contains duplicate candle timestamps"
                )

            frame.index = frame.index.tz_convert(IST_TIMEZONE)
            frame = frame.sort_index()

            if interval == "1h" and validate_hourly:
                validate_hourly_observations(frame)

            # This is a decoded DataFrame-size estimate, not exact wire bytes.
            try:
                estimated_bytes = int(frame.memory_usage(index=True, deep=True).sum())
                record_bandwidth(
                    "yahoo_finance", requests=1, estimated_inbound_bytes=estimated_bytes
                )
            except Exception:
                logger.debug("Yahoo bandwidth estimate unavailable", exc_info=True)

            stored = self._store(key, frame)
            self._mark_provenance(provenance, source="fresh", age_seconds=0.0, cache_key=self._key_id(key))
            return stored

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def in_backoff(self, symbol: str | None = None) -> bool:
        with self._lock:
            now = time.monotonic()
            if symbol is not None:
                return now < max(
                    self._backoff_until.get(symbol, 0.0),
                    self._global_backoff_until,
                )
            return (
                now < self._global_backoff_until
                or any(now < until for until in self._backoff_until.values())
            )


_default_provider = YahooProvider()


def fetch_yahoo(
    symbol: str,
    *,
    period: str = "5d",
    interval: str = "1h",
    validate_hourly: bool = True,
) -> pd.DataFrame:
    return _default_provider.fetch(
        symbol,
        period=period,
        interval=interval,
        validate_hourly=validate_hourly,
    )
