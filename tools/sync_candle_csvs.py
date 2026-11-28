"""Seed and incrementally update local historical candle CSVs from Yahoo Finance."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import LIVE_ASSETS
from yahoo_provider import YahooProvider

DEFAULT_SERIES: tuple[tuple[str, str], ...] = (
    ("1d", "2y"),
    ("1h", "60d"),
    ("30m", "60d"),
)


def sync_all(output_dir: Path, *, symbols: list[str] | None = None) -> tuple[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    provider = YahooProvider(
        persist_cache=False,
        csv_dir=output_dir,
        local_cache_dir=output_dir,
    )
    wanted = {s.strip().upper() for s in symbols} if symbols else None
    yahoo_symbols = sorted({
        asset.yahoo_symbol
        for asset in LIVE_ASSETS
        if wanted is None or asset.symbol.upper() in wanted or asset.yahoo_symbol.upper() in wanted
    })
    updated = 0
    failed = 0
    for yf_symbol in yahoo_symbols:
        for interval, period in DEFAULT_SERIES:
            try:
                # Force an upstream tail check by skipping the short memory/CSV TTL.
                existing = provider._load_csv_pair(yf_symbol, interval)
                tail_period = period
                if existing is not None and not existing[0].empty:
                    tail_period = provider._incremental_period(existing[0], interval, period)
                frame = provider._download_and_normalize(yf_symbol, period=tail_period, interval=interval, validate_hourly=False, priority=5)
                if existing is not None and not existing[0].empty and tail_period != period:
                    merged = provider._merge_csv_frames(existing[0], frame)
                    if merged is None:
                        frame = provider._download_and_normalize(yf_symbol, period=period, interval=interval, validate_hourly=False, priority=5)
                    else:
                        frame = merged
                provider._save_csv(yf_symbol, interval, frame)
                updated += 1
                print(f"OK {yf_symbol} {interval}: {len(frame)} rows")
            except Exception as exc:
                failed += 1
                print(f"WARN {yf_symbol} {interval}: {exc}")
    return updated, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=str(ROOT / "data" / "candles"),
        help="Directory holding <symbol>__<interval>.csv files",
    )
    parser.add_argument("--symbol", action="append", help="Optional symbol filter (repeatable)")
    args = parser.parse_args()
    updated, failed = sync_all(Path(args.dir), symbols=args.symbol)
    print(f"Candle CSV sync complete | updated={updated} failed={failed}")
    return 0 if updated > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
