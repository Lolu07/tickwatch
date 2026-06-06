import os
from dataclasses import dataclass, field


@dataclass
class Config:
    aws_region: str = field(
        default_factory=lambda: os.getenv("AWS_REGION", "us-east-1")
    )
    window_table_name: str = field(
        default_factory=lambda: os.environ["WINDOW_TABLE"]
    )
    anomaly_table_name: str = field(
        default_factory=lambda: os.environ["ANOMALY_TABLE"]
    )
    # How many prices to keep in the rolling window per symbol
    window_size: int = field(
        default_factory=lambda: int(os.getenv("WINDOW_SIZE", "50"))
    )
    # |z-score| must exceed this to be flagged as an anomaly
    zscore_threshold: float = field(
        default_factory=lambda: float(os.getenv("ZSCORE_THRESHOLD", "3.0"))
    )
    # Minimum window before detection runs (too few points → unreliable stddev)
    min_window_size: int = field(
        default_factory=lambda: int(os.getenv("MIN_WINDOW_SIZE", "10"))
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    # Phase 5: Claude API — secret name is None when explanations are disabled
    claude_secret_name: str = field(
        default_factory=lambda: os.getenv("CLAUDE_SECRET_NAME", "")
    )
    claude_timeout: float = field(
        default_factory=lambda: float(os.getenv("CLAUDE_TIMEOUT", "8.0"))
    )
