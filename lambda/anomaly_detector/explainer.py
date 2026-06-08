"""
Claude-powered plain-English explanations for detected price anomalies.

Key design decisions (interview context):
    Singleton client: the Anthropic SDK client and the boto3 Secrets Manager
    client are initialised on cold start and reused across warm invocations —
    avoiding the TLS handshake and SDK init cost on every record.

    Secrets Manager over env vars: API keys placed in Lambda environment
    variables appear in plaintext in the console and in CloudTrail.  Secrets
    Manager encrypts at rest and rotates independently.  An env-var fallback
    (CLAUDE_API_KEY) is retained for local development and CI.

    Best-effort: every error path returns None.  The anomaly detection pipeline
    must never fail because the LLM annotation step fails.  Explanation is
    enrichment, not a correctness dependency.

    Short max_tokens: 120 tokens is ample for one sentence and keeps p99
    latency well inside the Lambda timeout budget.
"""

import logging
import os
from typing import Optional

import anthropic
import boto3
from botocore.exceptions import ClientError

try:
    from .models import AnomalyRecord
except ImportError:
    from models import AnomalyRecord

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None

_SYSTEM = (
    "You are a quantitative trading analyst reviewing real-time price data. "
    "When given an anomaly, respond with exactly one sentence that states: "
    "the direction and magnitude of the price move, and one specific thing a "
    "trader should watch as a follow-up. No bullet points, no hedging language."
)


def _load_api_key(secret_name: Optional[str]) -> Optional[str]:
    """Retrieve Claude API key: CLAUDE_API_KEY env var first (dev), then Secrets Manager (prod)."""
    if key := os.getenv("CLAUDE_API_KEY"):
        return key
    if not secret_name:
        return None
    try:
        sm = boto3.client("secretsmanager")
        return sm.get_secret_value(SecretId=secret_name)["SecretString"]
    except ClientError as exc:
        logger.warning(
            "Secrets Manager retrieval failed (%s) — Claude explanations disabled",
            exc.response["Error"]["Code"],
        )
        return None


def init_client(secret_name: Optional[str], timeout: float) -> Optional[anthropic.Anthropic]:
    """
    Initialise the module-level Anthropic client singleton.
    Called once from handler.py at module scope (cold start).
    Subsequent calls are no-ops because the global is already set.
    """
    global _client
    if _client is not None:
        return _client

    api_key = _load_api_key(secret_name)
    if not api_key:
        logger.info("No Claude API key found — anomaly explanations disabled")
        return None

    _client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
    logger.info("Anthropic client initialised (timeout=%.1fs)", timeout)
    return _client


def explain_anomaly(record: AnomalyRecord) -> Optional[str]:
    """
    Ask Claude to explain an anomaly in plain English.
    Returns None when the client is unavailable or the API call fails.
    Never raises — caller should treat the return value as optional enrichment.
    """
    if _client is None:
        return None

    direction = "upward" if record.z_score > 0 else "downward"
    pct = abs((record.price - record.mean) / record.mean * 100) if record.mean else 0.0

    prompt = (
        f"Price anomaly — {record.symbol}:\n"
        f"  Direction: {direction} spike ({pct:.2f}% from rolling mean)\n"
        f"  Price:     ${record.price:.4f}  (mean ${record.mean:.4f}, σ {record.stddev:.4f})\n"
        f"  Z-score:   {record.z_score:+.2f}  (threshold ±{record.threshold:.1f})\n"
        f"  Window:    {record.window_size} trades\n\n"
        "In one sentence: what does this signal, and what should a trader watch next?"
    )

    try:
        # Haiku: deliberately chosen over Sonnet/Opus — one-sentence explanations
        # are high-volume and latency-sensitive; Haiku's quality is sufficient here.
        resp = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip() if resp.content else ""
        return text or None
    except Exception as exc:
        logger.warning("Claude explanation failed for %s@%d: %s", record.symbol, record.timestamp_ms, exc)
        return None
