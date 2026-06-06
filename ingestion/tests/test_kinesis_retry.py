"""
Tests for the retry and dead-letter logic in KinesisPublisher.
All boto3 calls are patched — no AWS credentials needed.
"""

import json
from unittest.mock import MagicMock, patch

from src.config import Config
from src.kinesis_publisher import KinesisPublisher
from src.models import Trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**overrides):
    defaults = dict(
        finnhub_api_key="k",
        kinesis_stream_name="test-stream",
        aws_region="us-east-1",
        symbols=["AAPL"],
        ws_heartbeat_interval=30,
        kinesis_batch_size=500,
        kinesis_flush_interval=999,  # disable periodic flush
        kinesis_max_retries=2,
        kinesis_retry_base_delay_ms=0,  # zero delay so tests run instantly
        log_level="DEBUG",
    )
    defaults.update(overrides)
    cfg = Config.__new__(Config)
    cfg.__dict__.update(defaults)
    return cfg


def _trade(symbol="AAPL", price=100.0):
    return Trade(symbol=symbol, price=price, volume=1.0,
                 timestamp_ms=1_700_000_000_000, trade_conditions=[])


def _success_result():
    return {"SequenceNumber": "49590338271490256608559692538361571095921575989136588898"}


def _throttle_result():
    return {"ErrorCode": "ProvisionedThroughputExceededException",
            "ErrorMessage": "Rate exceeded for shard shardId-000000000000"}


def _hard_fail_result():
    return {"ErrorCode": "ValidationException",
            "ErrorMessage": "Record is too large"}


# ---------------------------------------------------------------------------
# All records succeed on first attempt
# ---------------------------------------------------------------------------

@patch("src.kinesis_publisher.boto3.client")
def test_all_succeed_no_retry(mock_boto):
    mock_client = MagicMock()
    mock_client.put_records.return_value = {
        "FailedRecordCount": 0,
        "Records": [_success_result(), _success_result()],
    }
    mock_boto.return_value = mock_client

    pub = KinesisPublisher(_cfg())
    pub._send_with_retry([_trade(), _trade(symbol="MSFT")])
    pub.close()

    assert mock_client.put_records.call_count == 1
    assert pub.stats["total_published"] == 2
    assert pub.stats["total_failed"] == 0


# ---------------------------------------------------------------------------
# Partial failure → retry only failed records
# ---------------------------------------------------------------------------

@patch("src.kinesis_publisher.time.sleep")
@patch("src.kinesis_publisher.boto3.client")
def test_partial_throttle_retried(mock_boto, mock_sleep):
    mock_client = MagicMock()

    # First call: record[0] throttled, record[1] ok
    # Second call (retry of 1 record): succeeds
    mock_client.put_records.side_effect = [
        {"FailedRecordCount": 1, "Records": [_throttle_result(), _success_result()]},
        {"FailedRecordCount": 0, "Records": [_success_result()]},
    ]
    mock_boto.return_value = mock_client

    pub = KinesisPublisher(_cfg())
    trades = [_trade("AAPL"), _trade("MSFT")]
    pub._send_with_retry(trades)
    pub.close()

    assert mock_client.put_records.call_count == 2

    # Second call should only contain the 1 failed record (AAPL)
    second_call_records = mock_client.put_records.call_args_list[1][1]["Records"]
    assert len(second_call_records) == 1
    data = json.loads(second_call_records[0]["Data"])
    assert data["symbol"] == "AAPL"

    assert pub.stats["total_published"] == 2
    assert pub.stats["total_failed"] == 0


# ---------------------------------------------------------------------------
# Hard (non-retryable) failure → dead-lettered immediately, no retry
# ---------------------------------------------------------------------------

@patch("src.kinesis_publisher.boto3.client")
def test_hard_failure_not_retried(mock_boto):
    mock_client = MagicMock()
    mock_client.put_records.return_value = {
        "FailedRecordCount": 1,
        "Records": [_hard_fail_result()],
    }
    mock_boto.return_value = mock_client

    pub = KinesisPublisher(_cfg(kinesis_max_retries=3))
    pub._send_with_retry([_trade()])
    pub.close()

    # Hard failures must NOT be retried — only 1 PutRecords call
    assert mock_client.put_records.call_count == 1
    assert pub.stats["total_failed"] == 1
    assert pub.stats["total_published"] == 0


# ---------------------------------------------------------------------------
# Exhausted retries → dead-lettered after max_retries
# ---------------------------------------------------------------------------

@patch("src.kinesis_publisher.time.sleep")
@patch("src.kinesis_publisher.boto3.client")
def test_exhausted_retries_dead_lettered(mock_boto, mock_sleep):
    mock_client = MagicMock()
    # Always throttle — every attempt fails
    mock_client.put_records.return_value = {
        "FailedRecordCount": 1,
        "Records": [_throttle_result()],
    }
    mock_boto.return_value = mock_client

    pub = KinesisPublisher(_cfg(kinesis_max_retries=2))
    pub._send_with_retry([_trade()])
    pub.close()

    # 1 initial attempt + 2 retries = 3 total
    assert mock_client.put_records.call_count == 3
    assert pub.stats["total_failed"] == 1
    assert pub.stats["total_published"] == 0


# ---------------------------------------------------------------------------
# Call-level retryable ClientError (whole call rejected)
# ---------------------------------------------------------------------------

@patch("src.kinesis_publisher.time.sleep")
@patch("src.kinesis_publisher.boto3.client")
def test_call_level_throttle_retried(mock_boto, mock_sleep):
    from botocore.exceptions import ClientError

    # side_effect list items must be exception *instances* (not functions) to be raised.
    mock_client = MagicMock()
    mock_client.put_records.side_effect = [
        ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": ""}},
            "PutRecords",
        ),
        {"FailedRecordCount": 0, "Records": [_success_result()]},
    ]
    mock_boto.return_value = mock_client

    pub = KinesisPublisher(_cfg())
    pub._send_with_retry([_trade()])
    pub.close()

    assert mock_client.put_records.call_count == 2
    assert pub.stats["total_published"] == 1
    assert pub.stats["total_failed"] == 0


# ---------------------------------------------------------------------------
# Call-level non-retryable ClientError (access denied)
# ---------------------------------------------------------------------------

@patch("src.kinesis_publisher.boto3.client")
def test_access_denied_not_retried(mock_boto):
    from botocore.exceptions import ClientError

    mock_client = MagicMock()
    mock_client.put_records.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "User is not authorized"}},
        "PutRecords",
    )
    mock_boto.return_value = mock_client

    pub = KinesisPublisher(_cfg(kinesis_max_retries=3))
    pub._send_with_retry([_trade()])
    pub.close()

    assert mock_client.put_records.call_count == 1
    assert pub.stats["total_failed"] == 1
