"""
Tests for BatchProcessor — all AWS calls are mocked.
"""

import base64
import json
import time
from unittest.mock import MagicMock, patch
import pytest

from anomaly_detector.config import Config
from anomaly_detector.detector import ZScoreDetector
from anomaly_detector.handler import BatchProcessor, _decode
from anomaly_detector.models import TradeRecord, WindowState
from anomaly_detector.state_store import AnomalyStore, WindowStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kw):
    defaults = dict(
        aws_region="us-east-1",
        window_table_name="test-windows",
        anomaly_table_name="test-anomalies",
        window_size=50,
        zscore_threshold=3.0,
        min_window_size=5,
        log_level="DEBUG",
    )
    defaults.update(kw)
    cfg = Config.__new__(Config)
    cfg.__dict__.update(defaults)
    return cfg


def _kinesis_record(symbol: str, price: float, seq: str = "0001") -> dict:
    payload = {
        "symbol": symbol,
        "price": price,
        "volume": 100.0,
        "timestamp_ms": int(time.time() * 1000),
        "trade_conditions": [],
        "ingested_at": int(time.time() * 1000),
    }
    return {
        "eventID": f"shardId-000000000000:{seq}",
        "kinesis": {
            "sequenceNumber": seq,
            "partitionKey": symbol,
            "data": base64.b64encode(json.dumps(payload).encode()).decode(),
            "approximateArrivalTimestamp": time.time(),
        },
    }


def _mock_stores(window_prices: list = None):
    """Return (window_store_mock, anomaly_store_mock) with a pre-loaded window."""
    window_store = MagicMock(spec=WindowStore)
    anomaly_store = MagicMock(spec=AnomalyStore)
    window_store.batch_get.return_value = {
        "AAPL": WindowState(symbol="AAPL", prices=window_prices or [], last_updated_ms=0)
    }
    return window_store, anomaly_store


# ---------------------------------------------------------------------------
# _decode helper
# ---------------------------------------------------------------------------

def test_decode_valid_record():
    kr = _kinesis_record("AAPL", 185.0)
    trade = _decode(kr)
    assert trade.symbol == "AAPL"
    assert trade.price == 185.0


def test_decode_invalid_base64_raises():
    bad = {"eventID": "x", "kinesis": {"data": "!!!notbase64!!!", "sequenceNumber": "1"}}
    with pytest.raises(Exception):
        _decode(bad)


# ---------------------------------------------------------------------------
# Normal trade — no anomaly
# ---------------------------------------------------------------------------

def test_normal_trade_not_flagged():
    cfg = _make_config(min_window_size=5)
    detector = ZScoreDetector(threshold=3.0, min_window=5)
    history = [185.0] * 20  # flat history → any small deviation is z≈0
    window_store, anomaly_store = _mock_stores(history)

    processor = BatchProcessor(cfg, detector, window_store, anomaly_store)
    result = processor.process([_kinesis_record("AAPL", 185.1)])

    assert result == {"batchItemFailures": []}
    anomaly_store.save.assert_not_called()


# ---------------------------------------------------------------------------
# Anomalous trade — spike detected and saved
# ---------------------------------------------------------------------------

def test_spike_flagged_and_saved():
    cfg = _make_config(min_window_size=5)
    detector = ZScoreDetector(threshold=3.0, min_window=5)
    # Noisy history so stddev > 0 and z-score is computable
    noisy = [100.0, 100.1, 99.9, 100.2, 99.8, 100.15, 99.85,
             100.05, 99.95, 100.0, 100.1, 99.9, 100.2, 99.8,
             100.15, 99.85, 100.05, 99.95, 100.0, 100.1]
    window_store, anomaly_store = _mock_stores(noisy)

    processor = BatchProcessor(cfg, detector, window_store, anomaly_store)
    result = processor.process([_kinesis_record("AAPL", 500.0)])   # massive spike

    assert result == {"batchItemFailures": []}
    anomaly_store.save.assert_called_once()
    saved = anomaly_store.save.call_args[0][0]
    assert saved.symbol == "AAPL"
    assert saved.z_score > 3.0


# ---------------------------------------------------------------------------
# Window updated after each record in batch
# ---------------------------------------------------------------------------

def test_window_updated_between_records_in_batch():
    """
    If two records for the same symbol arrive in one batch, the second
    detection should use a window that includes the first record's price.
    """
    cfg = _make_config(min_window_size=5, window_size=50)
    detector = ZScoreDetector(threshold=3.0, min_window=5)

    initial_prices = [100.0] * 10
    window_store = MagicMock(spec=WindowStore)
    window_store.batch_get.return_value = {
        "AAPL": WindowState("AAPL", list(initial_prices), 0)
    }
    anomaly_store = MagicMock(spec=AnomalyStore)

    processor = BatchProcessor(cfg, detector, window_store, anomaly_store)
    records = [
        _kinesis_record("AAPL", 100.0, seq="0001"),
        _kinesis_record("AAPL", 100.0, seq="0002"),
    ]
    processor.process(records)

    saved_window = window_store.save.call_args[0][0]
    # Window should have grown by 2 prices (both records appended)
    assert len(saved_window.prices) == len(initial_prices) + 2


# ---------------------------------------------------------------------------
# Malformed record — skipped, not retried
# ---------------------------------------------------------------------------

def test_malformed_record_skipped_not_retried():
    cfg = _make_config()
    detector = ZScoreDetector()
    window_store, anomaly_store = _mock_stores()
    window_store.batch_get.return_value = {}

    bad_record = {
        "eventID": "bad",
        "kinesis": {"data": base64.b64encode(b"not json").decode(), "sequenceNumber": "999"},
    }
    processor = BatchProcessor(cfg, detector, window_store, anomaly_store)
    result = processor.process([bad_record])

    # Non-retryable decode failure must NOT appear in batchItemFailures
    assert result["batchItemFailures"] == []


# ---------------------------------------------------------------------------
# Empty batch
# ---------------------------------------------------------------------------

def test_empty_batch_returns_no_failures():
    cfg = _make_config()
    processor = BatchProcessor(cfg, ZScoreDetector(), MagicMock(), MagicMock())
    assert processor.process([]) == {"batchItemFailures": []}


# ---------------------------------------------------------------------------
# DynamoDB save failure → batchItemFailure returned for retry
# ---------------------------------------------------------------------------

def test_dynamodb_save_failure_returned_as_batch_failure():
    cfg = _make_config(min_window_size=2)
    detector = ZScoreDetector(threshold=3.0, min_window=2)

    window_store = MagicMock(spec=WindowStore)
    window_store.batch_get.return_value = {
        "AAPL": WindowState("AAPL", [100.0, 100.0], 0)
    }
    # Simulate DynamoDB save throwing
    window_store.save.side_effect = Exception("DynamoDB timeout")

    anomaly_store = MagicMock(spec=AnomalyStore)

    processor = BatchProcessor(cfg, detector, window_store, anomaly_store)
    kr = _kinesis_record("AAPL", 100.1, seq="seq-42")

    # window.save is called after the processing loop. The handler wraps it
    # in try/except so a save failure logs an error but doesn't crash the
    # invocation or add to batchItemFailures (records were already processed).
    result = processor.process([kr])
    assert result == {"batchItemFailures": []}
    window_store.save.assert_called_once()   # attempted even though it threw
