"""
DynamoDB-backed rolling window store and anomaly store.

State management rationale (interview context):
    Lambda is stateless — each invocation starts with a fresh execution
    environment. We persist the rolling price window in DynamoDB so it
    survives across invocations (and across Lambda container recycling).

Concurrency safety:
    With a single Kinesis shard, Lambda processes one batch at a time — no
    two invocations process the same shard concurrently. Partition key =
    symbol ensures all ticks for AAPL land on shard-0 and are delivered to
    Lambda in sequence. If you scale to N shards, you'd map symbols to shards
    consistently (e.g. hash(symbol) % N), preserving the invariant. Only a
    multi-shard fan-in to a single Lambda would require optimistic locking.

DynamoDB type note:
    boto3's DynamoDB resource rejects Python floats. Prices are serialised to
    a JSON string to avoid importing Decimal throughout the codebase.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError

try:
    from .config import Config
    from .models import AnomalyRecord, WindowState
except ImportError:
    from config import Config
    from models import AnomalyRecord, WindowState

logger = logging.getLogger(__name__)

# Anomaly records expire after 30 days (DynamoDB TTL).
_ANOMALY_TTL_SECONDS = 30 * 24 * 3600


class WindowStore:
    """Reads and writes the rolling price window for each symbol."""

    def __init__(self, config: Config):
        self._config = config
        resource = boto3.resource("dynamodb", region_name=config.aws_region)
        self._table = resource.Table(config.window_table_name)
        # Keep the resource handle for batch_get_item (table-level API lacks it)
        self._resource = resource

    def batch_get(self, symbols: List[str]) -> Dict[str, WindowState]:
        """
        Fetch windows for all symbols in one BatchGetItem call.
        Falls back to empty WindowState for symbols not yet in the table.
        DynamoDB BatchGetItem limit: 100 keys per call — well above our 8-symbol default.
        """
        if not symbols:
            return {}

        try:
            resp = self._resource.batch_get_item(
                RequestItems={
                    self._config.window_table_name: {
                        "Keys": [{"symbol": s} for s in symbols],
                        "ConsistentRead": True,
                    }
                }
            )
        except ClientError as exc:
            logger.error("batch_get_item failed: %s — using empty windows", exc)
            return {s: WindowState.empty(s) for s in symbols}

        result: Dict[str, WindowState] = {}
        for item in resp["Responses"].get(self._config.window_table_name, []):
            sym = item["symbol"]
            prices = json.loads(item.get("prices_json", "[]"))
            result[sym] = WindowState(
                symbol=sym,
                prices=[float(p) for p in prices],
                last_updated_ms=int(item.get("updated_at", 0)),
            )

        for sym in symbols:
            if sym not in result:
                result[sym] = WindowState.empty(sym)

        return result

    def save(self, state: WindowState) -> None:
        """Persist the window, trimming to the configured max size."""
        trimmed = state.prices[-self._config.window_size :]
        try:
            self._table.put_item(
                Item={
                    "symbol": state.symbol,
                    "prices_json": json.dumps(trimmed),
                    "updated_at": int(time.time() * 1000),
                }
            )
        except ClientError as exc:
            logger.error("put_item failed for window %s: %s", state.symbol, exc)


class AnomalyStore:
    """Writes detected anomaly records to DynamoDB."""

    def __init__(self, config: Config):
        resource = boto3.resource("dynamodb", region_name=config.aws_region)
        self._table = resource.Table(config.anomaly_table_name)

    def save(self, record: AnomalyRecord) -> None:
        # detected_date is the partition key for the "detected-date-index" GSI.
        # The API Lambda queries this GSI to return "all recent anomalies" across
        # all symbols without a full table scan.
        detected_date = datetime.fromtimestamp(
            record.detected_at_ms / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%d")

        try:
            self._table.put_item(
                Item={
                    "symbol": record.symbol,
                    "timestamp_ms": record.timestamp_ms,
                    "detected_date": detected_date,
                    # Store floats as strings — avoids boto3 Decimal requirement
                    "price": str(record.price),
                    "z_score": str(record.z_score),
                    "mean": str(record.mean),
                    "stddev": str(record.stddev),
                    "window_size": record.window_size,
                    "detected_at_ms": record.detected_at_ms,
                    "detector_name": record.detector_name,
                    "threshold": str(record.threshold),
                    # TTL: auto-delete after 30 days
                    "expires_at": int(time.time()) + _ANOMALY_TTL_SECONDS,
                    # Optional LLM annotation — omitted when Claude is unavailable
                    **( {"explanation": record.explanation} if record.explanation else {} ),
                }
            )
        except ClientError as exc:
            logger.error(
                "put_item failed for anomaly %s@%d: %s",
                record.symbol, record.timestamp_ms, exc,
            )
