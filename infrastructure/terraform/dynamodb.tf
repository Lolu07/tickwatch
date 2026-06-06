# ---------------------------------------------------------------------------
# DynamoDB tables
#
# Two tables with distinct access patterns:
#   tickwatch-windows  — rolling price window per symbol (read+write every invocation)
#   tickwatch-anomalies — detected anomalies for the dashboard (write-heavy, read on demand)
#
# Billing: PAY_PER_REQUEST (on-demand) is right here. During market hours the
# Lambda runs ~1,000 invocations/day; on-demand is cheaper than provisioned
# at that scale and removes the need to forecast RCU/WCU.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "price_windows" {
  name         = "tickwatch-windows-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "symbol"

  attribute {
    name = "symbol"
    type = "S"
  }

  # Point-in-time recovery not needed — this data is derived from Kinesis
  # and can be rebuilt by replaying the stream.
  point_in_time_recovery {
    enabled = false
  }

  tags = { Purpose = "Rolling price window for z-score anomaly detection" }
}

resource "aws_dynamodb_table" "anomalies" {
  name         = "tickwatch-anomalies-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "symbol"
  range_key    = "timestamp_ms"

  attribute {
    name = "symbol"
    type = "S"
  }

  attribute {
    name = "timestamp_ms"
    type = "N"
  }

  # TTL: the Lambda sets expires_at = now + 30 days.
  # DynamoDB deletes expired items automatically (within ~48h of expiry).
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  # GSI: query "all recent anomalies" for the dashboard without knowing the symbol.
  # Pattern: store a fixed date string (YYYY-MM-DD) as detected_date.
  # The dashboard queries this GSI for today's date, sorted by timestamp.
  # This avoids a full table scan while keeping the query simple.
  global_secondary_index {
    name            = "detected-date-index"
    hash_key        = "detected_date"
    range_key       = "timestamp_ms"
    projection_type = "ALL"
  }

  attribute {
    name = "detected_date"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true  # anomaly history is valuable — enable PITR
  }

  tags = { Purpose = "Detected price anomalies for dashboard and alerting" }
}
