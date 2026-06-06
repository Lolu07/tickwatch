import os
from dataclasses import dataclass, field


@dataclass
class Config:
    aws_region: str = field(
        default_factory=lambda: os.getenv("AWS_REGION", "us-east-1")
    )
    anomaly_table_name: str = field(
        default_factory=lambda: os.environ["ANOMALY_TABLE"]
    )
    window_table_name: str = field(
        default_factory=lambda: os.environ["WINDOW_TABLE"]
    )
    # Symbols the ingestion service subscribes to — used by /symbols fallback
    known_symbols: list = field(
        default_factory=lambda: os.getenv(
            "SYMBOLS", "AAPL,MSFT,GOOGL,AMZN,TSLA,META,NVDA,SPY"
        ).split(",")
    )
    default_limit: int = field(
        default_factory=lambda: int(os.getenv("DEFAULT_LIMIT", "50"))
    )
    max_limit: int = field(
        default_factory=lambda: int(os.getenv("MAX_LIMIT", "200"))
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
