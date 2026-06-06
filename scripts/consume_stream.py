#!/usr/bin/env python3
"""
consume_stream.py — real-time Kinesis consumer for local verification.

Opens a shard iterator on every shard and prints each trade event as it
arrives.  Use this alongside the ingestion service to confirm data is
flowing end-to-end through the pipeline.

Usage:
    python scripts/consume_stream.py
    python scripts/consume_stream.py --stream tickwatch-trades-dev --region us-east-1
    python scripts/consume_stream.py --from-beginning   # replay all retained records
    python scripts/consume_stream.py --symbol AAPL      # filter to one ticker

Reads KINESIS_STREAM_NAME / AWS_REGION from .env (or the environment) if
the flags are not supplied.

Exit: Ctrl-C to stop cleanly.
"""

import argparse
import json
import os
import sys
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Colour helpers (gracefully disabled if stdout is not a tty)
# ---------------------------------------------------------------------------

_COLOUR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text

def green(t):  return _c("92", t)
def yellow(t): return _c("93", t)
def cyan(t):   return _c("96", t)
def bold(t):   return _c("1",  t)
def dim(t):    return _c("2",  t)
def red(t):    return _c("91", t)

# Map ticker → colour so each symbol gets a consistent colour in output
_SYMBOL_COLOURS = ["92", "93", "96", "95", "94", "91", "33", "36"]
_symbol_colour_cache: Dict[str, str] = {}

def symbol_colour(sym: str) -> str:
    if sym not in _symbol_colour_cache:
        idx = len(_symbol_colour_cache) % len(_SYMBOL_COLOURS)
        _symbol_colour_cache[sym] = _SYMBOL_COLOURS[idx]
    return _symbol_colour_cache[sym]

def coloured_symbol(sym: str) -> str:
    return _c(symbol_colour(sym), f"{sym:<5}")


# ---------------------------------------------------------------------------
# .env loader (mirrors ingestion/main.py so no extra deps needed)
# ---------------------------------------------------------------------------

def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


# ---------------------------------------------------------------------------
# Stats tracker
# ---------------------------------------------------------------------------

class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.total = 0
        self.per_symbol: Dict[str, int] = defaultdict(int)
        self.per_shard: Dict[str, int] = defaultdict(int)
        self.start = time.time()

    def record(self, symbol: str, shard_id: str) -> None:
        with self._lock:
            self.total += 1
            self.per_symbol[symbol] += 1
            self.per_shard[shard_id] += 1

    def summary(self) -> str:
        with self._lock:
            elapsed = time.time() - self.start
            rate = self.total / elapsed if elapsed > 0 else 0
            top = sorted(self.per_symbol.items(), key=lambda x: -x[1])[:5]
            top_str = "  ".join(f"{s}:{n}" for s, n in top)
            return (
                f"{bold('Total')}: {self.total}  "
                f"{bold('Rate')}: {rate:.1f}/s  "
                f"{bold('Top symbols')}: {top_str or '—'}"
            )


# ---------------------------------------------------------------------------
# Shard reader — one thread per shard
# ---------------------------------------------------------------------------

class ShardReader(threading.Thread):
    # Kinesis allows 5 GetRecords calls/s per shard — stay well under.
    POLL_INTERVAL_S = 0.25

    def __init__(
        self,
        kinesis_client,
        stream_name: str,
        shard_id: str,
        iterator_type: str,
        stats: Stats,
        symbol_filter: Optional[str],
    ):
        super().__init__(daemon=True, name=f"shard-{shard_id[-4:]}")
        self._client = kinesis_client
        self._stream = stream_name
        self._shard_id = shard_id
        self._iterator_type = iterator_type
        self._stats = stats
        self._symbol_filter = symbol_filter
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        iterator = self._get_iterator()
        if not iterator:
            return

        short_id = self._shard_id[-6:]
        print(dim(f"  [shard {short_id}] reader started ({self._iterator_type})"))

        while not self._stop.is_set() and iterator:
            try:
                resp = self._client.get_records(ShardIterator=iterator, Limit=100)
            except self._client.exceptions.ExpiredIteratorException:
                print(yellow(f"  [shard {short_id}] iterator expired — renewing"))
                iterator = self._get_iterator()
                continue
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code == "ProvisionedThroughputExceededException":
                    time.sleep(1)
                    continue
                print(red(f"  [shard {short_id}] GetRecords error: {exc}"))
                time.sleep(2)
                continue

            records = resp.get("Records", [])
            iterator = resp.get("NextShardIterator")

            for rec in records:
                self._print_record(rec, short_id)

            # Shard is empty — wait before polling again
            if not records:
                time.sleep(self.POLL_INTERVAL_S)

    def _get_iterator(self) -> Optional[str]:
        try:
            resp = self._client.get_shard_iterator(
                StreamName=self._stream,
                ShardId=self._shard_id,
                ShardIteratorType=self._iterator_type,
            )
            return resp["ShardIterator"]
        except ClientError as exc:
            print(red(f"  [shard {self._shard_id[-6:]}] get_shard_iterator error: {exc}"))
            return None

    def _print_record(self, rec: dict, short_shard: str) -> None:
        try:
            payload = json.loads(rec["Data"])
        except (json.JSONDecodeError, KeyError):
            print(red(f"  [shard {short_shard}] unreadable record: {rec!r:.200}"))
            return

        symbol = payload.get("symbol", "?")
        if self._symbol_filter and symbol != self._symbol_filter:
            return

        self._stats.record(symbol, self._shard_id)

        # Human-readable ingestion lag
        ingested_at = payload.get("ingested_at", 0)
        trade_ts    = payload.get("timestamp_ms", 0)
        lag_ms      = ingested_at - trade_ts if ingested_at and trade_ts else 0

        ts_str = (
            datetime.fromtimestamp(ingested_at / 1000, tz=timezone.utc)
            .strftime("%H:%M:%S.%f")[:-3]
            if ingested_at else "—"
        )

        price  = payload.get("price",  0.0)
        volume = payload.get("volume", 0.0)
        conds  = payload.get("trade_conditions", [])
        cond_str = f"  cond={conds}" if conds else ""

        print(
            f"  {dim(ts_str)}  "
            f"{coloured_symbol(symbol)}  "
            f"${bold(f'{price:>10.4f}')}  "
            f"vol={volume:<8.1f}  "
            f"shard={dim(short_shard)}  "
            f"lag={lag_ms:>5}ms"
            f"{cond_str}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TickWatch — Kinesis stream consumer")
    p.add_argument("--stream",  default=None, help="Stream name (overrides env)")
    p.add_argument("--region",  default=None, help="AWS region (overrides env)")
    p.add_argument(
        "--from-beginning",
        action="store_true",
        help="Use TRIM_HORIZON to replay all retained records (default: LATEST)",
    )
    p.add_argument("--symbol", default=None, help="Filter output to one ticker symbol")
    p.add_argument(
        "--stats-interval",
        type=int, default=15,
        help="Print a stats summary every N seconds (0 = disable)",
    )
    return p.parse_args()


def list_shards(client, stream_name: str) -> List[str]:
    shards = []
    kwargs: dict = {"StreamName": stream_name}
    while True:
        resp = client.list_shards(**kwargs)
        for shard in resp["Shards"]:
            shards.append(shard["ShardId"])
        token = resp.get("NextToken")
        if not token:
            break
        kwargs = {"NextToken": token}   # NextToken call must NOT include StreamName
    return shards


def main() -> None:
    # Load .env from project root (two levels up from scripts/)
    _load_env(Path(__file__).resolve().parents[1] / ".env")

    args = parse_args()

    stream_name = args.stream or os.getenv("KINESIS_STREAM_NAME", "tickwatch-trades-dev")
    region      = args.region or os.getenv("AWS_REGION", "us-east-1")
    iter_type   = "TRIM_HORIZON" if args.from_beginning else "LATEST"

    print(bold("\n  TickWatch — Kinesis stream consumer"))
    print(f"  stream  : {cyan(stream_name)}")
    print(f"  region  : {cyan(region)}")
    print(f"  mode    : {cyan(iter_type)}")
    if args.symbol:
        print(f"  filter  : {yellow(args.symbol)} only")
    print()

    client = boto3.client("kinesis", region_name=region)

    # Verify stream is active before starting readers
    try:
        resp = client.describe_stream_summary(StreamName=stream_name)
        status = resp["StreamDescriptionSummary"]["StreamStatus"]
        shard_count = resp["StreamDescriptionSummary"]["OpenShardCount"]
        if status != "ACTIVE":
            print(red(f"  Stream status is '{status}' — expected ACTIVE. Aborting."))
            sys.exit(1)
        print(green(f"  Stream ACTIVE  ({shard_count} shard{'s' if shard_count != 1 else ''})"))
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "ResourceNotFoundException":
            print(red(f"\n  Stream '{stream_name}' not found in {region}."))
            print(yellow("  Checklist:"))
            print("    1. Run `terraform apply` — the stream may not exist yet")
            print("    2. Confirm KINESIS_STREAM_NAME in .env matches terraform output stream_name")
            print("    3. Confirm AWS_REGION matches the region where you applied Terraform")
        elif code in ("AccessDeniedException", "UnauthorizedException"):
            print(red(f"\n  Access denied: {exc}"))
            print(yellow("  Fix: attach the tickwatch-kinesis-consumer policy to your IAM user/role"))
            print("  Required actions: kinesis:GetRecords, kinesis:GetShardIterator,")
            print("                    kinesis:DescribeStream, kinesis:ListShards")
        else:
            print(red(f"\n  AWS error: {exc}"))
        sys.exit(1)

    # Discover shards
    try:
        shard_ids = list_shards(client, stream_name)
    except ClientError as exc:
        print(red(f"  list_shards error: {exc}"))
        sys.exit(1)

    print(f"  Shards  : {', '.join(dim(s[-8:]) for s in shard_ids)}")
    print()
    print(dim("  Waiting for records… (Ctrl-C to stop)"))
    print(dim("  " + "─" * 70))

    stats = Stats()
    readers = [
        ShardReader(client, stream_name, sid, iter_type, stats, args.symbol)
        for sid in shard_ids
    ]
    for r in readers:
        r.start()

    # Stats printer thread
    def _stats_loop():
        while True:
            time.sleep(args.stats_interval)
            print(dim(f"\n  ── {stats.summary()} ──\n"))

    if args.stats_interval > 0:
        t = threading.Thread(target=_stats_loop, daemon=True)
        t.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"\n\n  {bold('Stopped.')}  {stats.summary()}\n")
        for r in readers:
            r.stop()


if __name__ == "__main__":
    main()
