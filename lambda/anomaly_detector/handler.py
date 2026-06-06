"""
Lambda entry point — triggered by Kinesis Data Streams.

Kinesis batch format received by Lambda:
{
  "Records": [
    {
      "kinesis": {
        "sequenceNumber": "49590338...",
        "partitionKey": "AAPL",        ← the symbol
        "data": "<base64 JSON>",       ← our TradeRecord payload
        "approximateArrivalTimestamp": 1234567890.123
      },
      "eventID": "shardId-000000000000:49590338...",
      ...
    }
  ]
}

Partial batch failure (ReportBatchItemFailures):
    If one record fails, we return its sequenceNumber in batchItemFailures.
    Kinesis retries only from that point, rather than re-delivering the
    entire batch. This prevents a single bad record from blocking the shard.
    Enabled via function_response_types = ["ReportBatchItemFailures"] in
    the Terraform event source mapping.

Cold start vs warm start:
    Module-level objects (_config, _detector, _window_store, _anomaly_store,
    and the Anthropic client) are initialised once when the Lambda container
    is created and reused across warm invocations. This avoids re-constructing
    boto3 clients and the Anthropic TLS connection on every call.
"""

import base64
import json
import logging
import time
from typing import Dict, List, Tuple

try:
    from .config import Config                                           # package context (tests, local)
    from .detector import BaseDetector, ZScoreDetector
    from .explainer import explain_anomaly, init_client
    from .models import AnomalyRecord, DetectionResult, TradeRecord, WindowState
    from .state_store import AnomalyStore, WindowStore
except ImportError:
    from config import Config                                            # Lambda flat-module context
    from detector import BaseDetector, ZScoreDetector
    from explainer import explain_anomaly, init_client
    from models import AnomalyRecord, DetectionResult, TradeRecord, WindowState
    from state_store import AnomalyStore, WindowStore

# ---------------------------------------------------------------------------
# Module-level singletons — initialised on cold start, reused on warm starts
# ---------------------------------------------------------------------------

_config = Config()

logging.basicConfig(level=_config.log_level)
logger = logging.getLogger(__name__)

_detector: BaseDetector = ZScoreDetector(
    threshold=_config.zscore_threshold,
    min_window=_config.min_window_size,
)
_window_store = WindowStore(_config)
_anomaly_store = AnomalyStore(_config)

# Anthropic client — None when CLAUDE_SECRET_NAME is unset or key is unavailable.
# Initialised once here; explain_anomaly() checks the module-level _client directly.
init_client(
    secret_name=_config.claude_secret_name or None,
    timeout=_config.claude_timeout,
)


# ---------------------------------------------------------------------------
# BatchProcessor — dependency-injected for testability
# ---------------------------------------------------------------------------

class BatchProcessor:
    """
    Processes a Kinesis batch end-to-end:
      1. Decode base64 records
      2. Batch-fetch rolling windows from DynamoDB
      3. Run anomaly detection on each trade in sequence order
      4. Persist updated windows and detected anomalies
      5. Return batchItemFailures for Kinesis retry

    Separating this from lambda_handler makes it unit-testable without
    mocking module globals.
    """

    def __init__(
        self,
        config: Config,
        detector: BaseDetector,
        window_store: WindowStore,
        anomaly_store: AnomalyStore,
    ):
        self._config    = config
        self._detector  = detector
        self._window_store  = window_store
        self._anomaly_store = anomaly_store

    def process(self, kinesis_records: list) -> dict:
        logger.info("Processing batch of %d Kinesis records", len(kinesis_records))

        # --- Step 1: decode -------------------------------------------------
        decoded: List[Tuple[dict, TradeRecord]] = []
        for kr in kinesis_records:
            try:
                trade = _decode(kr)
                decoded.append((kr, trade))
            except Exception as exc:
                # Decode failures are non-retryable (malformed data in stream).
                # Log and skip — do NOT add to batchItemFailures or Kinesis
                # will retry indefinitely.
                logger.error(
                    "Non-retryable decode failure for event %s: %s",
                    kr.get("eventID"), exc,
                )

        if not decoded:
            return {"batchItemFailures": []}

        # --- Step 2: batch-fetch windows ------------------------------------
        symbols = list({trade.symbol for _, trade in decoded})
        windows: Dict[str, WindowState] = self._window_store.batch_get(symbols)

        # --- Step 3: process in Kinesis sequence order ----------------------
        # Kinesis guarantees records within a shard are ordered by sequence
        # number. We process in that order so each price is appended to the
        # window before the next record uses it.
        failed_items = []
        anomalies: List[AnomalyRecord] = []

        for kr, trade in decoded:
            try:
                window = windows[trade.symbol]
                result = self._detector.detect(trade.price, window.prices)

                if result.is_anomaly:
                    _log_anomaly(trade, result)
                    record = _make_anomaly_record(trade, result)
                    record.explanation = explain_anomaly(record)
                    anomalies.append(record)

                # Append new price and trim; the updated window is used by
                # subsequent records for the same symbol within this batch.
                window.prices.append(trade.price)
                window.prices = window.prices[-self._config.window_size :]
                window.last_updated_ms = trade.timestamp_ms

            except Exception as exc:
                logger.error(
                    "Retryable error processing %s@%d: %s",
                    trade.symbol, trade.timestamp_ms, exc,
                )
                failed_items.append(
                    {"itemIdentifier": kr["kinesis"]["sequenceNumber"]}
                )

        # --- Step 4: persist ------------------------------------------------
        # Save failures here are non-fatal for the current batch — records
        # were already processed. Log loudly but don't add to batchItemFailures
        # (that would cause Kinesis to re-deliver already-processed records).
        for window in windows.values():
            if window.prices:
                try:
                    self._window_store.save(window)
                except Exception as exc:
                    logger.error("Failed to save window for %s: %s", window.symbol, exc)

        for anomaly in anomalies:
            try:
                self._anomaly_store.save(anomaly)
            except Exception as exc:
                logger.error("Failed to save anomaly %s@%d: %s",
                             anomaly.symbol, anomaly.timestamp_ms, exc)

        if failed_items:
            logger.warning(
                "Returning %d batchItemFailures for Kinesis retry", len(failed_items)
            )

        logger.info(
            "Batch complete — processed=%d anomalies=%d failures=%d",
            len(decoded), len(anomalies), len(failed_items),
        )
        return {"batchItemFailures": failed_items}


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    processor = BatchProcessor(
        config=_config,
        detector=_detector,
        window_store=_window_store,
        anomaly_store=_anomaly_store,
    )
    return processor.process(event.get("Records", []))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode(kinesis_record: dict) -> TradeRecord:
    raw = base64.b64decode(kinesis_record["kinesis"]["data"]).decode("utf-8")
    return TradeRecord.from_kinesis_payload(json.loads(raw))


def _make_anomaly_record(trade: TradeRecord, result: DetectionResult) -> AnomalyRecord:
    return AnomalyRecord(
        symbol=trade.symbol,
        price=trade.price,
        z_score=result.score,
        mean=result.mean,
        stddev=result.stddev,
        window_size=result.window_size,
        timestamp_ms=trade.timestamp_ms,
        detected_at_ms=int(time.time() * 1000),
        detector_name=result.detector_name,
        threshold=result.threshold,
    )


def _log_anomaly(trade: TradeRecord, result: DetectionResult) -> None:
    """
    Emit a structured JSON log line to CloudWatch.
    Use CloudWatch Logs Insights to query:
        fields @timestamp, symbol, price, z_score
        | filter event = "ANOMALY_DETECTED"
        | sort @timestamp desc
    """
    logger.warning(
        json.dumps({
            "event": "ANOMALY_DETECTED",
            "symbol": trade.symbol,
            "price": trade.price,
            "z_score": result.score,
            "mean": result.mean,
            "stddev": result.stddev,
            "window_size": result.window_size,
            "threshold": result.threshold,
            "detector": result.detector_name,
            "trade_timestamp_ms": trade.timestamp_ms,
        })
    )
