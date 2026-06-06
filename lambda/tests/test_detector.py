import math
import pytest
from anomaly_detector.detector import ZScoreDetector


@pytest.fixture
def detector():
    return ZScoreDetector(threshold=3.0, min_window=5)


# ---------------------------------------------------------------------------
# Window size gating
# ---------------------------------------------------------------------------

def test_below_min_window_never_flags(detector):
    history = [100.0, 102.0, 98.0]   # only 3 prices, min_window=5
    result = detector.detect(500.0, history)
    assert not result.is_anomaly
    assert result.score == 0.0
    assert result.window_size == 3


def test_exactly_at_min_window_enables_detection(detector):
    history = [100.0] * 5             # exactly min_window prices
    result = detector.detect(100.0, history)
    assert result.window_size == 5
    # flat history → stddev ≈ 0, z-score = 0
    assert result.score == 0.0


# ---------------------------------------------------------------------------
# Normal prices — no anomaly
# ---------------------------------------------------------------------------

def test_price_within_threshold_not_flagged(detector):
    history = [100.0, 101.0, 99.5, 100.5, 100.2, 99.8, 100.1, 100.3, 99.9, 100.0]
    result = detector.detect(100.4, history)
    assert not result.is_anomaly
    assert abs(result.score) < 3.0


def test_result_fields_populated(detector):
    history = [100.0] * 10
    result = detector.detect(100.0, history)
    assert result.detector_name == "zscore"
    assert result.threshold == 3.0
    assert result.mean == pytest.approx(100.0)
    assert result.stddev == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Price spikes — anomaly
# ---------------------------------------------------------------------------

def test_large_upward_spike_flagged(detector):
    # Realistic noisy history so stddev > 0 and z-score is meaningful
    history = [100.0, 100.1, 99.9, 100.2, 99.8, 100.15, 99.85,
               100.05, 99.95, 100.0, 100.1, 99.9, 100.2, 99.8,
               100.15, 99.85, 100.05, 99.95, 100.0, 100.1]
    result = detector.detect(200.0, history)   # +100% spike
    assert result.is_anomaly
    assert result.score > 3.0


def test_large_downward_crash_flagged(detector):
    history = [100.0, 100.1, 99.9, 100.2, 99.8, 100.15, 99.85,
               100.05, 99.95, 100.0, 100.1, 99.9, 100.2, 99.8,
               100.15, 99.85, 100.05, 99.95, 100.0, 100.1]
    result = detector.detect(10.0, history)    # -90% crash
    assert result.is_anomaly
    assert result.score < -3.0


def test_spike_just_above_threshold():
    det = ZScoreDetector(threshold=2.0, min_window=5)
    # Build a history with known mean and stddev
    history = [10.0] * 10   # mean=10, stddev=0 — inject slight noise
    noisy = [10.0, 10.1, 9.9, 10.05, 9.95, 10.02, 9.98, 10.01, 9.99, 10.0]
    mean = sum(noisy) / len(noisy)
    variance = sum((p - mean) ** 2 for p in noisy) / len(noisy)
    stddev = math.sqrt(variance)
    # Price that is just above 2 stddev from mean
    spike = mean + 2.01 * stddev
    result = det.detect(spike, noisy)
    assert result.is_anomaly


def test_spike_just_below_threshold():
    det = ZScoreDetector(threshold=2.0, min_window=5)
    noisy = [10.0, 10.1, 9.9, 10.05, 9.95, 10.02, 9.98, 10.01, 9.99, 10.0]
    mean = sum(noisy) / len(noisy)
    variance = sum((p - mean) ** 2 for p in noisy) / len(noisy)
    stddev = math.sqrt(variance)
    normal = mean + 1.99 * stddev
    result = det.detect(normal, noisy)
    assert not result.is_anomaly


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_flat_history_no_false_positive(detector):
    # All prices identical → stddev = 0 → z-score guarded to 0
    history = [185.0] * 20
    result = detector.detect(185.0, history)
    assert result.score == 0.0
    assert not result.is_anomaly


def test_flat_history_spike_not_flagged_without_stddev(detector):
    # When stddev ≈ 0, any deviation would give infinite z.
    # Our guard returns score=0 to avoid false positives from degenerate windows.
    history = [100.0] * 20
    result = detector.detect(101.0, history)
    assert result.score == 0.0


def test_name_property():
    assert ZScoreDetector().name == "zscore"


def test_min_window_property():
    det = ZScoreDetector(min_window=15)
    assert det.min_window_size == 15
