import json
import logging
import random
import time
import threading
from typing import List, Tuple

import boto3
from botocore.exceptions import ClientError

from .models import Trade
from .config import Config

logger = logging.getLogger(__name__)

# Kinesis returns these error codes for transient failures that are safe to retry.
# ProvisionedThroughputExceededException → shard is saturated, back off and retry.
# InternalFailure → AWS-side transient error, also retryable.
_RETRYABLE_ERROR_CODES = {"ProvisionedThroughputExceededException", "InternalFailure"}

# Kinesis hard limits per PutRecords call.
_MAX_RECORDS_PER_CALL = 500
_MAX_BYTES_PER_CALL = 5 * 1024 * 1024  # 5 MB


class KinesisPublisher:
    """
    Buffers Trade records and flushes them to Kinesis Data Streams via PutRecords.

    Architecture notes (for interview context):
    - PutRecords sends up to 500 records in one HTTP call, amortising per-request overhead.
    - Partition key = ticker symbol → all ticks for AAPL land on the same shard, preserving
      intra-symbol ordering for the downstream z-score Lambda.
    - PutRecords is *partially atomic*: some records in a batch can fail while others succeed.
      The retry loop isolates and re-sends only the failed subset, avoiding duplicate delivery
      of already-acknowledged records.
    - Back-off uses full jitter (random in [0, cap]) rather than pure exponential to spread
      thundering-herd retries across multiple producer instances.
    """

    def __init__(self, config: Config):
        self._config = config
        self._client = boto3.client("kinesis", region_name=config.aws_region)
        self._buffer: List[Trade] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(target=self._periodic_flush, daemon=True)
        self._flush_thread.start()
        self._total_published = 0
        self._total_failed = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put(self, trade: Trade) -> None:
        with self._lock:
            self._buffer.append(trade)
            should_flush = len(self._buffer) >= self._config.kinesis_batch_size

        if should_flush:
            self._flush()

    def flush(self) -> None:
        self._flush()

    def close(self) -> None:
        """Flush remaining records and stop the background thread cleanly."""
        self._stop_event.set()
        self._flush_thread.join(timeout=5)
        self._flush()

    @property
    def stats(self) -> dict:
        return {
            "total_published": self._total_published,
            "total_failed": self._total_failed,
            "buffer_size": len(self._buffer),
        }

    # ------------------------------------------------------------------
    # Internal — flush pipeline
    # ------------------------------------------------------------------

    def _periodic_flush(self) -> None:
        while not self._stop_event.wait(self._config.kinesis_flush_interval):
            self._flush()

    def _flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            batch, self._buffer = self._buffer, []

        for i in range(0, len(batch), _MAX_RECORDS_PER_CALL):
            self._send_with_retry(batch[i : i + _MAX_RECORDS_PER_CALL])

    # ------------------------------------------------------------------
    # Internal — PutRecords with per-record retry
    # ------------------------------------------------------------------

    def _build_records(self, trades: List[Trade]) -> List[dict]:
        return [
            {
                "Data": json.dumps(t.to_kinesis_record()).encode(),
                "PartitionKey": t.partition_key,
            }
            for t in trades
        ]

    def _send_with_retry(self, trades: List[Trade]) -> None:
        """
        Send a chunk of trades to Kinesis, retrying only the failed subset on each attempt.

        Retry strategy:
          attempt 0 → send all trades
          attempt 1 → retry only the records that failed with a retryable error code
          attempt 2 → same, smaller subset
          ...after max_retries → dead-letter any remaining failures (log + count)

        Back-off: full jitter = random(0, base * 2^attempt), capped at 30 s.
        """
        pending_trades = trades
        max_retries = self._config.kinesis_max_retries
        base_delay_s = self._config.kinesis_retry_base_delay_ms / 1000.0

        for attempt in range(max_retries + 1):
            if attempt > 0:
                cap = min(base_delay_s * (2 ** attempt), 30.0)
                sleep_s = random.uniform(0, cap)
                logger.info(
                    "Retry attempt %d/%d for %d records — sleeping %.2fs",
                    attempt, max_retries, len(pending_trades), sleep_s,
                )
                time.sleep(sleep_s)

            pending_trades, succeeded, hard_failed = self._put_records(pending_trades)
            self._total_published += succeeded

            if hard_failed:
                # Non-retryable errors (e.g. record too large): dead-letter immediately.
                self._dead_letter(hard_failed, "non-retryable Kinesis error")
                self._total_failed += len(hard_failed)

            if not pending_trades:
                return  # all records accepted

        # Exhausted retries — dead-letter whatever is still pending.
        logger.error(
            "Exhausted %d retries — dead-lettering %d records",
            max_retries, len(pending_trades),
        )
        self._dead_letter(pending_trades, "max retries exceeded")
        self._total_failed += len(pending_trades)

    def _put_records(
        self, trades: List[Trade]
    ) -> Tuple[List[Trade], int, List[Trade]]:
        """
        Call PutRecords once and partition the results into three buckets:
          retryable  — failed with a transient error (returned as first element)
          succeeded  — count of successfully accepted records
          hard_failed — failed with a non-retryable error

        Returns (retryable_trades, succeeded_count, hard_failed_trades).
        """
        records = self._build_records(trades)
        try:
            resp = self._client.put_records(
                StreamName=self._config.kinesis_stream_name,
                Records=records,
            )
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in _RETRYABLE_ERROR_CODES:
                # Whole-call transient failure — retry the entire batch.
                logger.warning("PutRecords call-level error (retryable): %s", exc)
                return trades, 0, []
            # Non-retryable call-level error (e.g. access denied, stream not found).
            logger.error("PutRecords call-level error (non-retryable): %s", exc)
            return [], 0, trades

        retryable: List[Trade] = []
        hard_failed: List[Trade] = []
        succeeded = 0

        for trade, result in zip(trades, resp["Records"]):
            if "SequenceNumber" in result:
                succeeded += 1
            else:
                code = result.get("ErrorCode", "Unknown")
                if code in _RETRYABLE_ERROR_CODES:
                    retryable.append(trade)
                else:
                    logger.warning(
                        "Non-retryable record error for %s: %s — %s",
                        trade.symbol, code, result.get("ErrorMessage"),
                    )
                    hard_failed.append(trade)

        if retryable:
            logger.warning(
                "PutRecords partial failure: %d retryable, %d hard failures, %d ok",
                len(retryable), len(hard_failed), succeeded,
            )
        else:
            logger.debug("Published %d records to Kinesis", succeeded)

        return retryable, succeeded, hard_failed

    def _dead_letter(self, trades: List[Trade], reason: str) -> None:
        """
        Emit a structured log entry for each undeliverable record.
        In production you would forward these to an SQS DLQ or S3.
        """
        for trade in trades:
            logger.error(
                "DEAD_LETTER reason=%s symbol=%s price=%.4f ts=%d",
                reason, trade.symbol, trade.price, trade.timestamp_ms,
            )
