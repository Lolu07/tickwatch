"""
API Lambda — serves the React dashboard via HTTP API Gateway v2.

Routes:
    GET /anomalies              — recent anomalies (optionally filtered by symbol or date)
    GET /anomalies/{symbol}     — anomalies for a single ticker
    GET /windows/{symbol}       — rolling price window (for the price chart)
    GET /symbols                — list of symbols that have anomaly or window data

Response envelope (all routes):
    Every response wraps its payload in a consistent envelope so the frontend
    and any future consumers have a stable contract.  The 'explanation' field
    on each anomaly is null today but reserved for a Phase 5 LLM annotation
    — adding it later requires no API or frontend restructuring.

    {
      "data": { ... },          ← route-specific payload
      "meta": {
        "query_ms": 42,
        "count": 12,            ← where applicable
        "version": "1"
      }
    }

CORS:
    Handled by API Gateway (configured in Terraform).  The Lambda itself does
    not set CORS headers — keeping routing and transport concerns separate.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from .config import Config

# ---------------------------------------------------------------------------
# Module-level singletons — reused across warm invocations
# ---------------------------------------------------------------------------

_config = Config()
logging.basicConfig(level=_config.log_level)
logger = logging.getLogger(__name__)

_dynamodb = boto3.resource("dynamodb", region_name=_config.aws_region)
_anomaly_table = _dynamodb.Table(_config.anomaly_table_name)
_window_table = _dynamodb.Table(_config.window_table_name)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    t0 = time.monotonic()
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"].rstrip("/") or "/"
    qs = event.get("queryStringParameters") or {}
    path_params = event.get("pathParameters") or {}

    logger.info("%s %s qs=%s", method, path, qs)

    try:
        if method == "GET" and path == "/anomalies":
            body, count = _get_anomalies(qs)
        elif method == "GET" and path.startswith("/anomalies/"):
            symbol = path_params.get("symbol") or path.split("/anomalies/", 1)[1]
            body, count = _get_anomalies_by_symbol(symbol.upper(), qs)
        elif method == "GET" and path.startswith("/windows/"):
            symbol = path_params.get("symbol") or path.split("/windows/", 1)[1]
            body, count = _get_window(symbol.upper())
        elif method == "GET" and path == "/symbols":
            body, count = _get_symbols()
        else:
            return _response(404, {"error": f"Route not found: {method} {path}"}, 0, 0)

    except ClientError as exc:
        logger.error("DynamoDB error: %s", exc)
        return _response(500, {"error": "Upstream data store error"}, 0, 0)
    except Exception as exc:
        logger.exception("Unhandled error: %s", exc)
        return _response(500, {"error": "Internal server error"}, 0, 0)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return _response(200, body, elapsed_ms, count)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def _get_anomalies(qs: dict):
    """
    Return recent anomalies across all symbols, querying the GSI by date.
    Queries today and yesterday so results don't go empty at midnight.
    """
    limit = min(int(qs.get("limit", _config.default_limit)), _config.max_limit)

    now_utc = datetime.now(tz=timezone.utc)
    dates = [
        now_utc.strftime("%Y-%m-%d"),
        (now_utc - timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    items = []
    for date_str in dates:
        if len(items) >= limit:
            break
        resp = _anomaly_table.query(
            IndexName="detected-date-index",
            KeyConditionExpression=Key("detected_date").eq(date_str),
            ScanIndexForward=False,
            Limit=limit - len(items),
        )
        items.extend(resp.get("Items", []))

    anomalies = [_format_anomaly(i) for i in items[:limit]]
    return {"anomalies": anomalies}, len(anomalies)


def _get_anomalies_by_symbol(symbol: str, qs: dict):
    """Return anomalies for a single ticker, newest first."""
    limit = min(int(qs.get("limit", _config.default_limit)), _config.max_limit)
    resp = _anomaly_table.query(
        KeyConditionExpression=Key("symbol").eq(symbol),
        ScanIndexForward=False,
        Limit=limit,
    )
    anomalies = [_format_anomaly(i) for i in resp.get("Items", [])]
    return {"symbol": symbol, "anomalies": anomalies}, len(anomalies)


def _get_window(symbol: str):
    """
    Return the rolling price window for a symbol.
    The dashboard uses this to draw the price chart background line,
    with anomaly events overlaid as scatter points.
    """
    resp = _window_table.get_item(
        Key={"symbol": symbol},
        ConsistentRead=True,
    )
    item = resp.get("Item")
    if not item:
        return {"symbol": symbol, "prices": [], "updated_at": None}, 0

    prices_raw = json.loads(item.get("prices_json", "[]"))
    prices = [float(p) for p in prices_raw]
    updated_at = int(item.get("updated_at", 0))

    # Synthesise approximate timestamps for each price point.
    # The producer emits ~2 ticks/symbol/s; 500ms spacing gives a realistic timeline.
    tick_interval_ms = 500
    price_points = [
        {
            "time": updated_at - (len(prices) - 1 - i) * tick_interval_ms,
            "price": p,
        }
        for i, p in enumerate(prices)
    ]

    return {
        "symbol": symbol,
        "prices": price_points,
        "updated_at": updated_at,
    }, len(prices)


def _get_symbols():
    """
    Scan the windows table for all symbols that have been seen.
    Falls back to the configured symbol list if the table is empty.
    The windows table is tiny (one item per symbol) so scan is fine.
    """
    resp = _window_table.scan(ProjectionExpression="#sym", ExpressionAttributeNames={"#sym": "symbol"})
    items = resp.get("Items", [])
    symbols = sorted(i["symbol"] for i in items) if items else sorted(_config.known_symbols)
    return {"symbols": symbols}, len(symbols)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_anomaly(item: dict) -> dict:
    """
    Convert a raw DynamoDB item to the canonical API anomaly shape.

    The 'explanation' field is null now but reserved for Phase 5 — when an
    LLM annotates each anomaly with a plain-English reason, it populates this
    field in DynamoDB and the API surfaces it here with no schema change.
    """
    return {
        "symbol": item["symbol"],
        "price": float(item.get("price", 0)),
        "z_score": float(item.get("z_score", 0)),
        "mean": float(item.get("mean", 0)),
        "stddev": float(item.get("stddev", 0)),
        "window_size": int(item.get("window_size", 0)),
        "timestamp_ms": int(item.get("timestamp_ms", 0)),
        "detected_at_ms": int(item.get("detected_at_ms", 0)),
        "detector_name": item.get("detector_name", "zscore"),
        "threshold": float(item.get("threshold", 3.0)),
        # Reserved for LLM annotation — surfaced here so frontend never needs
        # an API version bump when it's populated.
        "explanation": item.get("explanation"),
    }


def _response(status: int, body: dict, elapsed_ms: int, count: int) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "data": body,
            "meta": {
                "query_ms": elapsed_ms,
                "count": count,
                "version": "1",
            },
        }),
    }
