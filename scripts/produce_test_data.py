#!/usr/bin/env python3
"""
produce_test_data.py — inject synthetic trade ticks into Kinesis for pipeline testing.

Generates realistic-looking OHLC-style random walks for each configured symbol
and publishes them to the stream at a configurable rate.  Use this outside
market hours to verify the full ingestion → Kinesis → consumer path.

Usage:
    python scripts/produce_test_data.py
    python scripts/produce_test_data.py --rate 5 --count 50
    python scripts/produce_test_data.py --symbols AAPL,TSLA --rate 2
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ---------------------------------------------------------------------------
# Realistic seed prices for each symbol
# ---------------------------------------------------------------------------

SEED_PRICES = {
    "AAPL":  185.00,
    "MSFT":  415.00,
    "GOOGL": 175.00,
    "AMZN":  195.00,
    "TSLA":  250.00,
    "META":  510.00,
    "NVDA":  875.00,
    "SPY":   530.00,
}


def _next_price(current: float) -> float:
    """Random walk: ±0.05% per tick, roughly ~1% daily vol."""
    pct = random.gauss(0, 0.0005)
    return round(current * (1 + pct), 4)


def _make_tick(symbol: str, price: float) -> dict:
    return {
        "symbol": symbol,
        "price": price,
        "volume": round(random.uniform(1, 500), 1),
        "timestamp_ms": int(time.time() * 1000),
        "trade_conditions": random.choice([[], ["1"], ["2"]]),
        "ingested_at": int(time.time() * 1000),
    }


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

def publish_batch(client, stream_name: str, ticks: list[dict]) -> tuple[int, int]:
    records = [
        {
            "Data": json.dumps(t).encode(),
            "PartitionKey": t["symbol"],
        }
        for t in ticks
    ]
    try:
        resp = client.put_records(StreamName=stream_name, Records=records)
        failed = resp.get("FailedRecordCount", 0)
        return len(records) - failed, failed
    except ClientError as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        return 0, len(records)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TickWatch — synthetic trade producer")
    p.add_argument("--stream", default=None)
    p.add_argument("--region", default=None)
    p.add_argument("--symbols", default=None, help="Comma-separated list, e.g. AAPL,TSLA")
    p.add_argument("--rate",  type=float, default=2.0, help="Ticks per second (default 2)")
    p.add_argument("--count", type=int,   default=0,   help="Stop after N total ticks (0 = run forever)")
    return p.parse_args()


def main() -> None:
    _load_env(Path(__file__).resolve().parents[1] / ".env")
    args = parse_args()

    stream  = args.stream  or os.getenv("KINESIS_STREAM_NAME", "tickwatch-trades-dev")
    region  = args.region  or os.getenv("AWS_REGION", "us-east-1")
    symbols = (args.symbols or os.getenv("SYMBOLS", ",".join(SEED_PRICES))).split(",")
    interval = 1.0 / max(args.rate, 0.1)

    # Keep a running price for each symbol
    prices = {s: SEED_PRICES.get(s, 100.0) for s in symbols}

    client = boto3.client("kinesis", region_name=region)

    print(f"  Synthetic producer → {stream} ({region})")
    print(f"  Symbols : {', '.join(symbols)}")
    print(f"  Rate    : {args.rate} tick/s   Count: {'∞' if args.count == 0 else args.count}")
    print("  Ctrl-C to stop\n")

    total_ok = 0
    total_fail = 0
    sent = 0

    try:
        while True:
            # One tick per symbol per interval; batch the whole round together
            batch = []
            for sym in symbols:
                prices[sym] = _next_price(prices[sym])
                tick = _make_tick(sym, prices[sym])
                batch.append(tick)
                print(
                    f"  → {sym:<5}  ${tick['price']:>10.4f}"
                    f"  vol={tick['volume']:<6}"
                    f"  ts={tick['timestamp_ms']}"
                )

            ok, fail = publish_batch(client, stream, batch)
            total_ok   += ok
            total_fail += fail
            sent       += len(batch)

            if fail:
                print(f"  !! {fail} record(s) failed this batch")

            if args.count and sent >= args.count:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        pass

    print(f"\n  Done — published {total_ok} records, {total_fail} failed.")


if __name__ == "__main__":
    main()
