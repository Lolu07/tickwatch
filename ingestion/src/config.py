import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    finnhub_api_key: str = field(default_factory=lambda: os.environ["FINNHUB_API_KEY"])
    kinesis_stream_name: str = field(
        default_factory=lambda: os.getenv("KINESIS_STREAM_NAME", "tickwatch-trades")
    )
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "us-east-1"))
    symbols: List[str] = field(
        default_factory=lambda: os.getenv(
            "SYMBOLS", "AAPL,MSFT,GOOGL,AMZN,TSLA,META,NVDA,SPY"
        ).split(",")
    )
    # Reconnect after this many seconds of silence
    ws_heartbeat_interval: int = int(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))
    # Max records to buffer before flushing to Kinesis
    kinesis_batch_size: int = int(os.getenv("KINESIS_BATCH_SIZE", "100"))
    # Flush interval in seconds even if batch isn't full
    kinesis_flush_interval: float = float(os.getenv("KINESIS_FLUSH_INTERVAL", "1.0"))
    # How many times to retry a failed PutRecords sub-batch before dead-lettering
    kinesis_max_retries: int = int(os.getenv("KINESIS_MAX_RETRIES", "3"))
    # Base delay in ms for exponential back-off between retries (doubles each attempt)
    kinesis_retry_base_delay_ms: int = int(os.getenv("KINESIS_RETRY_BASE_DELAY_MS", "100"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
