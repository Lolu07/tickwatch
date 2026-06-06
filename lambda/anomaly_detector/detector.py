"""
Pluggable anomaly detection using the Strategy pattern.

Interview note: the handler depends on BaseDetector, not any concrete
implementation. To add a scikit-learn IsolationForest or LSTM-based detector,
subclass BaseDetector, implement detect(), and pass it to BatchProcessor.
No other code changes are needed.
"""

import math
from abc import ABC, abstractmethod

try:
    from .models import DetectionResult
except ImportError:
    from models import DetectionResult


class BaseDetector(ABC):
    """
    Interface every detector must satisfy.
    The handler is written against this interface alone.
    """

    @abstractmethod
    def detect(self, price: float, history: list[float]) -> DetectionResult:
        """
        Evaluate whether `price` is anomalous relative to `history`.
        `history` is the rolling window of *preceding* prices — it does NOT
        include `price` itself, so there is no look-ahead bias.
        """

    @property
    @abstractmethod
    def min_window_size(self) -> int:
        """Minimum history length before this detector produces meaningful output."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier written to logs and DynamoDB for traceability."""


class ZScoreDetector(BaseDetector):
    """
    Flags a price as anomalous when its z-score against the rolling window
    exceeds `threshold` standard deviations in either direction.

    Formula:
        μ = mean(history)
        σ = population_stddev(history)
        z = (price − μ) / σ

    Design trade-offs:
      + Simple and interpretable — z-score is universally understood
      + No training data required, works from the first window fill
      + Online-friendly: window update is O(1) amortised
      − Assumes roughly normal price distribution (fine for short windows)
      − Sensitive to window size — tune WINDOW_SIZE and MIN_WINDOW_SIZE for
        the target symbol's volatility profile

    To swap in scikit-learn IsolationForest:
        class IsolationForestDetector(BaseDetector):
            def __init__(self, contamination=0.01):
                self._model = IsolationForest(contamination=contamination)
                self._fitted = False
            def detect(self, price, history):
                if len(history) < self.min_window_size:
                    return DetectionResult(is_anomaly=False, ...)
                X = np.array(history + [price]).reshape(-1, 1)
                self._model.fit(X[:-1])
                score = self._model.decision_function([[price]])[0]
                return DetectionResult(is_anomaly=score < 0, score=score, ...)
    """

    def __init__(self, threshold: float = 3.0, min_window: int = 10):
        self._threshold = threshold
        self._min_window = min_window

    @property
    def min_window_size(self) -> int:
        return self._min_window

    @property
    def name(self) -> str:
        return "zscore"

    def detect(self, price: float, history: list[float]) -> DetectionResult:
        n = len(history)

        if n < self._min_window:
            return DetectionResult(
                is_anomaly=False,
                score=0.0,
                mean=price,
                stddev=0.0,
                window_size=n,
                detector_name=self.name,
                threshold=self._threshold,
            )

        mean = sum(history) / n
        # Population stddev: we treat the window as the full reference distribution,
        # not a sample from a larger population.
        variance = sum((p - mean) ** 2 for p in history) / n
        stddev = math.sqrt(variance)

        # Guard against a perfectly flat price series (stddev ≈ 0).
        z = (price - mean) / stddev if stddev > 1e-10 else 0.0

        return DetectionResult(
            is_anomaly=abs(z) > self._threshold,
            score=round(z, 6),
            mean=round(mean, 6),
            stddev=round(stddev, 6),
            window_size=n,
            detector_name=self.name,
            threshold=self._threshold,
        )
