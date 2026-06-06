import time
from src.models import Trade


RAW_TICK = {
    "s": "AAPL",
    "p": 185.23,
    "v": 100.0,
    "t": 1717000000000,
    "c": ["1"],
}


def test_from_finnhub_maps_fields():
    trade = Trade.from_finnhub(RAW_TICK)
    assert trade.symbol == "AAPL"
    assert trade.price == 185.23
    assert trade.volume == 100.0
    assert trade.timestamp_ms == 1717000000000
    assert trade.trade_conditions == ["1"]


def test_from_finnhub_missing_conditions():
    tick = {**RAW_TICK, "c": None}
    trade = Trade.from_finnhub(tick)
    assert trade.trade_conditions == []


def test_to_kinesis_record_contains_required_fields():
    trade = Trade.from_finnhub(RAW_TICK)
    before = int(time.time() * 1000)
    record = trade.to_kinesis_record()
    after = int(time.time() * 1000)

    assert record["symbol"] == "AAPL"
    assert record["price"] == 185.23
    assert before <= record["ingested_at"] <= after


def test_partition_key_is_symbol():
    trade = Trade.from_finnhub(RAW_TICK)
    assert trade.partition_key == "AAPL"
