import json
from unittest.mock import MagicMock, patch

from src.config import Config
from src.kinesis_publisher import KinesisPublisher
from src.models import Trade


def _make_config(**overrides):
    defaults = dict(
        finnhub_api_key="test-key",
        kinesis_stream_name="test-stream",
        aws_region="us-east-1",
        symbols=["AAPL"],
        ws_heartbeat_interval=30,
        kinesis_batch_size=3,
        kinesis_flush_interval=999,  # disable periodic flush in unit tests
        log_level="DEBUG",
    )
    defaults.update(overrides)
    cfg = Config.__new__(Config)
    cfg.__dict__.update(defaults)
    return cfg


def _make_trade(symbol="AAPL", price=100.0):
    return Trade(
        symbol=symbol, price=price, volume=10.0,
        timestamp_ms=1717000000000, trade_conditions=[]
    )


@patch("src.kinesis_publisher.boto3.client")
def test_flush_on_batch_size(mock_boto):
    mock_client = MagicMock()
    mock_client.put_records.return_value = {"FailedRecordCount": 0, "Records": []}
    mock_boto.return_value = mock_client

    cfg = _make_config(kinesis_batch_size=2)
    pub = KinesisPublisher(cfg)

    pub.put(_make_trade())
    mock_client.put_records.assert_not_called()

    pub.put(_make_trade())
    mock_client.put_records.assert_called_once()

    pub.close()


@patch("src.kinesis_publisher.boto3.client")
def test_records_sent_to_correct_stream(mock_boto):
    mock_client = MagicMock()
    mock_client.put_records.return_value = {"FailedRecordCount": 0, "Records": []}
    mock_boto.return_value = mock_client

    cfg = _make_config(kinesis_batch_size=1)
    pub = KinesisPublisher(cfg)
    pub.put(_make_trade(symbol="MSFT", price=420.0))
    pub.close()

    args, kwargs = mock_client.put_records.call_args
    assert kwargs["StreamName"] == "test-stream"
    record_data = json.loads(kwargs["Records"][0]["Data"])
    assert record_data["symbol"] == "MSFT"
    assert record_data["price"] == 420.0
    assert kwargs["Records"][0]["PartitionKey"] == "MSFT"
