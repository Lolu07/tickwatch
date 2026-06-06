# ---------------------------------------------------------------------------
# Lambda anomaly detector
#
# Deployment strategy: archive_file packages the lambda/ directory at apply
# time. source_code_hash ensures Terraform re-deploys when code changes.
# In a real CI/CD pipeline you'd upload a pre-built zip to S3 from CI and
# reference it here — that decouples infrastructure changes from code changes.
# ---------------------------------------------------------------------------

data "archive_file" "lambda_package" {
  type = "zip"

  # Package only the anomaly_detector source — not tests or dev deps
  source_dir  = "${path.root}/../../lambda/anomaly_detector"
  output_path = "${path.module}/lambda_package.zip"

  excludes = ["__pycache__", "*.pyc", "*.pyo"]
}

resource "aws_lambda_function" "anomaly_detector" {
  function_name    = "tickwatch-anomaly-detector-${var.environment}"
  role             = aws_iam_role.lambda_anomaly_detector.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda_package.output_path
  source_code_hash = data.archive_file.lambda_package.output_base64sha256

  # Timeout: Kinesis batch window is 5s; allow 60s total per invocation
  # to cover DynamoDB latency under load.
  timeout     = 60
  memory_size = 256

  environment {
    variables = {
      WINDOW_TABLE      = aws_dynamodb_table.price_windows.name
      ANOMALY_TABLE     = aws_dynamodb_table.anomalies.name
      WINDOW_SIZE       = "50"
      ZSCORE_THRESHOLD  = "3.0"
      MIN_WINDOW_SIZE   = "10"
      AWS_ACCOUNT_ID    = data.aws_caller_identity.current.account_id
      LOG_LEVEL         = var.environment == "prod" ? "WARNING" : "INFO"
      # Phase 5: Claude API — Lambda reads the key from Secrets Manager at cold start.
      # Unset or empty disables explanations gracefully (no error, no explanation field).
      CLAUDE_SECRET_NAME = aws_secretsmanager_secret.claude_api_key.name
      CLAUDE_TIMEOUT     = "8"
    }
  }

  # X-Ray active tracing: traces every invocation and DynamoDB call.
  # Visible in the AWS X-Ray console; useful for latency profiling.
  tracing_config {
    mode = "Active"
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_cloudwatch_log_group.lambda_logs,
  ]
}

data "aws_caller_identity" "current" {}

# Explicit log group so Terraform manages its lifecycle and retention.
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/tickwatch-anomaly-detector-${var.environment}"
  retention_in_days = 14
}

# CloudWatch Metric Filter: count anomaly events so you can graph them
# or alarm on a sudden spike in detections.
resource "aws_cloudwatch_log_metric_filter" "anomaly_count" {
  name           = "tickwatch-anomaly-count-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.lambda_logs.name
  # Matches the JSON log lines emitted by _log_anomaly() in handler.py
  pattern        = "{ $.event = \"ANOMALY_DETECTED\" }"

  metric_transformation {
    name      = "AnomalyCount"
    namespace = "TickWatch"
    value     = "1"
    unit      = "Count"
  }
}

# ---------------------------------------------------------------------------
# Kinesis event source mapping
#
# Key settings:
#   batch_size = 100           — up to 100 records per invocation
#   maximum_batching_window    — wait up to 5s to fill a batch (reduces invocations)
#   bisect_batch_on_function_error — if Lambda errors, retry with half the batch
#                                    to isolate the bad record
#   ReportBatchItemFailures    — handler returns failed sequence numbers so
#                                Kinesis only re-delivers the failed records
#   destination_config         — on_failure sends to SQS DLQ after all retries
# ---------------------------------------------------------------------------

resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn  = aws_kinesis_stream.trades.arn
  function_name     = aws_lambda_function.anomaly_detector.arn
  starting_position = "LATEST"

  batch_size                         = 100
  maximum_batching_window_in_seconds = 5
  bisect_batch_on_function_error     = true

  function_response_types = ["ReportBatchItemFailures"]

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.lambda_dlq.arn
    }
  }
}

# SQS dead-letter queue: receives the record batch if Lambda exhausts all
# retries. Inspect these to find poison-pill messages or persistent errors.
resource "aws_sqs_queue" "lambda_dlq" {
  name                      = "tickwatch-anomaly-detector-dlq-${var.environment}"
  message_retention_seconds = 1209600  # 14 days
}
