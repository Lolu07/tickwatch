from dataclasses import dataclass, field
from typing import List, Optional
import time


@dataclass
class TradeRecord:
    symbol: str
    price: float
    volume: float
    timestamp_ms: int
    trade_conditions: list
    ingested_at: int

    @classmethod
    def from_kinesis_payload(cls, payload: dict) -> "TradeRecord":
        return cls(
            symbol=payload["symbol"],
            price=float(payload["price"]),
            volume=float(payload["volume"]),
            timestamp_ms=int(payload["timestamp_ms"]),
            trade_conditions=payload.get("trade_conditions", []),
            ingested_at=int(payload.get("ingested_at", time.time() * 1000)),
        )


@dataclass
class DetectionResult:
    is_anomaly: bool
    score: float        # z-score for ZScoreDetector; model score for future detectors
    mean: float
    stddev: float
    window_size: int
    detector_name: str
    threshold: float


@dataclass
class WindowState:
    symbol: str
    prices: List[float]
    last_updated_ms: int

    @classmethod
    def empty(cls, symbol: str) -> "WindowState":
        return cls(symbol=symbol, prices=[], last_updated_ms=0)


@dataclass
class AnomalyRecord:
    symbol: str
    price: float
    z_score: float
    mean: float
    stddev: float
    window_size: int
    timestamp_ms: int
    detected_at_ms: int
    detector_name: str
    threshold: float
    explanation: Optional[str] = None
