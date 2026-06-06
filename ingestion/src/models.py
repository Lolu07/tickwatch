from dataclasses import dataclass, asdict
from typing import Optional
import time


@dataclass
class Trade:
    symbol: str
    price: float
    volume: float
    timestamp_ms: int      # milliseconds from Finnhub
    trade_conditions: list

    @classmethod
    def from_finnhub(cls, raw: dict) -> "Trade":
        return cls(
            symbol=raw["s"],
            price=raw["p"],
            volume=raw["v"],
            timestamp_ms=raw["t"],
            trade_conditions=raw.get("c") or [],
        )

    def to_kinesis_record(self) -> dict:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "volume": self.volume,
            "timestamp_ms": self.timestamp_ms,
            "trade_conditions": self.trade_conditions,
            "ingested_at": int(time.time() * 1000),
        }

    @property
    def partition_key(self) -> str:
        return self.symbol


@dataclass
class SubscriptionStatus:
    symbol: str
    status: str          # "subscribed" | "error"
    message: Optional[str] = None
