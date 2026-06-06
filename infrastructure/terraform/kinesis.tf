# ---------------------------------------------------------------------------
# Kinesis Data Stream — receives raw trade ticks from the ingestion service.
#
# Architecture note: we use PROVISIONED mode here because market-data volume
# is predictable during trading hours (9:30–16:00 ET). ON_DEMAND mode is a
# valid alternative if you prefer not to estimate shard count; it auto-scales
# but costs ~3× more per GB for typical bursty workloads.
# ---------------------------------------------------------------------------

resource "aws_kinesis_stream" "trades" {
  name             = "${var.stream_name}-${var.environment}"
  shard_count      = var.shard_count
  retention_period = var.retention_period_hours

  # Enhanced shard-level metrics give you per-shard throughput graphs in
  # CloudWatch without extra cost (IncomingRecords, WriteProvisionedThroughputExceeded).
  shard_level_metrics = [
    "IncomingBytes",
    "IncomingRecords",
    "OutgoingBytes",
    "OutgoingRecords",
    "WriteProvisionedThroughputExceeded",
    "ReadProvisionedThroughputExceeded",
    "IteratorAgeMilliseconds",
  ]

  # Server-side encryption with the AWS-managed Kinesis key.
  # Use a customer-managed KMS key in prod for tighter audit control.
  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"
}

# CloudWatch alarm: fires if any shard's write throughput is consistently
# above 80%. That's your cue to add another shard before drops start.
resource "aws_cloudwatch_metric_alarm" "write_throughput_high" {
  alarm_name          = "tickwatch-kinesis-write-throttle-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "WriteProvisionedThroughputExceeded"
  namespace           = "AWS/Kinesis"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Kinesis shard write throughput exceeded — consider adding shards"

  dimensions = {
    StreamName = aws_kinesis_stream.trades.name
  }
}
