# ---------------------------------------------------------------------------
# IAM — least-privilege policy for the ingestion service.
#
# Principle: the ingestion service only needs to *write* to Kinesis.
# It gets no read permissions — that's the Lambda consumer's job.
# Separating producer and consumer IAM roles limits blast radius if
# either credential is compromised.
# ---------------------------------------------------------------------------

# Policy document: allow PutRecord/PutRecords on our specific stream only.
data "aws_iam_policy_document" "kinesis_producer" {
  statement {
    sid    = "KinesisWrite"
    effect = "Allow"

    actions = [
      "kinesis:PutRecord",
      "kinesis:PutRecords",
      # DescribeStream lets the service validate the stream exists on startup.
      "kinesis:DescribeStream",
      "kinesis:DescribeStreamSummary",
    ]

    resources = [aws_kinesis_stream.trades.arn]
  }

  # KMS permission needed because we enabled SSE on the stream.
  statement {
    sid    = "KMSEncrypt"
    effect = "Allow"

    actions = [
      "kms:GenerateDataKey",
      "kms:Decrypt",
    ]

    resources = ["arn:aws:kms:${var.aws_region}:*:alias/aws/kinesis"]
  }
}

resource "aws_iam_policy" "kinesis_producer" {
  name        = "tickwatch-kinesis-producer-${var.environment}"
  description = "Allows the TickWatch ingestion service to write to the trades stream"
  policy      = data.aws_iam_policy_document.kinesis_producer.json
}

# ---------------------------------------------------------------------------
# Option A — ECS Task Role (preferred for containerised ingestion service).
# The task assumes this role; no long-lived access keys needed.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingestion_task" {
  name               = "${var.ingestion_service_role_name}-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
  description        = "ECS task role for the TickWatch ingestion service"
}

resource "aws_iam_role_policy_attachment" "ingestion_kinesis" {
  role       = aws_iam_role.ingestion_task.name
  policy_arn = aws_iam_policy.kinesis_producer.arn
}

# ---------------------------------------------------------------------------
# Option B — IAM User with access keys (local dev / non-ECS deployments).
# Used only in dev; in prod prefer the ECS task role above.
# ---------------------------------------------------------------------------

resource "aws_iam_user" "ingestion_dev" {
  count = var.environment == "dev" ? 1 : 0
  name  = "tickwatch-ingestion-dev"
  tags  = { Purpose = "Local development access keys for TickWatch ingestion service" }
}

resource "aws_iam_user_policy_attachment" "ingestion_dev_kinesis" {
  count      = var.environment == "dev" ? 1 : 0
  user       = aws_iam_user.ingestion_dev[0].name
  policy_arn = aws_iam_policy.kinesis_producer.arn
}

# Access keys are not stored in Terraform state for security.
# After apply, create keys manually:
#   aws iam create-access-key --user-name tickwatch-ingestion-dev

# ---------------------------------------------------------------------------
# Consumer policy — read-only access for local verification scripts and the
# Phase 3 Lambda.  Separate from the producer policy so each principal gets
# exactly the permissions it needs.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "kinesis_consumer" {
  statement {
    sid    = "KinesisRead"
    effect = "Allow"

    actions = [
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "kinesis:DescribeStream",
      "kinesis:DescribeStreamSummary",
      "kinesis:ListShards",
      "kinesis:ListStreams",
    ]

    resources = [aws_kinesis_stream.trades.arn]
  }

  # KMS Decrypt needed to read SSE-encrypted records.
  statement {
    sid    = "KMSDecrypt"
    effect = "Allow"
    actions = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:*:alias/aws/kinesis"]
  }
}

resource "aws_iam_policy" "kinesis_consumer" {
  name        = "tickwatch-kinesis-consumer-${var.environment}"
  description = "Read-only access to the TickWatch trades stream (verification scripts, Lambda)"
  policy      = data.aws_iam_policy_document.kinesis_consumer.json
}

# In dev, give the same user both producer and consumer rights so you can
# run ingestion + verification script from one set of credentials.
resource "aws_iam_user_policy_attachment" "ingestion_dev_consumer" {
  count      = var.environment == "dev" ? 1 : 0
  user       = aws_iam_user.ingestion_dev[0].name
  policy_arn = aws_iam_policy.kinesis_consumer.arn
}

# ---------------------------------------------------------------------------
# Lambda execution role — assumed by the anomaly detector function.
#
# Least-privilege breakdown:
#   AWSLambdaBasicExecutionRole — write logs to CloudWatch (AWS managed)
#   kinesis_consumer            — read from the trades stream (defined above)
#   lambda_dynamodb             — read/write windows and anomalies tables only
#   lambda_sqs                  — send to the DLQ on persistent failure
#   lambda_xray                 — send X-Ray trace segments
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_anomaly_detector" {
  name               = "tickwatch-lambda-anomaly-detector-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  description        = "Execution role for the TickWatch anomaly detector Lambda"
}

# CloudWatch Logs (included in the AWS managed basic execution policy)
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_anomaly_detector.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Kinesis read (reuses the consumer policy already defined above)
resource "aws_iam_role_policy_attachment" "lambda_kinesis" {
  role       = aws_iam_role.lambda_anomaly_detector.name
  policy_arn = aws_iam_policy.kinesis_consumer.arn
}

# DynamoDB — scoped to exactly the two tables this Lambda needs
data "aws_iam_policy_document" "lambda_dynamodb" {
  statement {
    sid    = "WindowsReadWrite"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:BatchGetItem",
    ]
    resources = [aws_dynamodb_table.price_windows.arn]
  }

  statement {
    sid    = "AnomaliesWrite"
    effect = "Allow"
    actions = ["dynamodb:PutItem"]
    resources = [
      aws_dynamodb_table.anomalies.arn,
      "${aws_dynamodb_table.anomalies.arn}/index/*",
    ]
  }
}

resource "aws_iam_policy" "lambda_dynamodb" {
  name        = "tickwatch-lambda-dynamodb-${var.environment}"
  description = "DynamoDB access for the anomaly detector Lambda"
  policy      = data.aws_iam_policy_document.lambda_dynamodb.json
}

resource "aws_iam_role_policy_attachment" "lambda_dynamodb" {
  role       = aws_iam_role.lambda_anomaly_detector.name
  policy_arn = aws_iam_policy.lambda_dynamodb.arn
}

# SQS — send failed batches to the DLQ
data "aws_iam_policy_document" "lambda_sqs" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.lambda_dlq.arn]
  }
}

resource "aws_iam_policy" "lambda_sqs" {
  name   = "tickwatch-lambda-sqs-${var.environment}"
  policy = data.aws_iam_policy_document.lambda_sqs.json
}

resource "aws_iam_role_policy_attachment" "lambda_sqs" {
  role       = aws_iam_role.lambda_anomaly_detector.name
  policy_arn = aws_iam_policy.lambda_sqs.arn
}

# X-Ray tracing
resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda_anomaly_detector.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# Secrets Manager — scoped to the single Claude API key secret only.
# Least-privilege: GetSecretValue on this ARN, nothing else.
data "aws_iam_policy_document" "lambda_secrets" {
  statement {
    sid     = "ReadClaudeApiKey"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.claude_api_key.arn]
  }
}

resource "aws_iam_policy" "lambda_secrets" {
  name        = "tickwatch-lambda-secrets-${var.environment}"
  description = "Allows the anomaly detector Lambda to read the Claude API key"
  policy      = data.aws_iam_policy_document.lambda_secrets.json
}

resource "aws_iam_role_policy_attachment" "lambda_secrets" {
  role       = aws_iam_role.lambda_anomaly_detector.name
  policy_arn = aws_iam_policy.lambda_secrets.arn
}

# ---------------------------------------------------------------------------
# API handler Lambda role — read-only access to both DynamoDB tables.
# No Kinesis or SQS access needed — this Lambda only serves the dashboard.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "lambda_api_handler" {
  name               = "tickwatch-lambda-api-handler-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  description        = "Execution role for the TickWatch dashboard API Lambda"
}

resource "aws_iam_role_policy_attachment" "api_handler_basic_execution" {
  role       = aws_iam_role.lambda_api_handler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "api_handler_dynamodb" {
  statement {
    sid    = "AnomaliesRead"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
    ]
    resources = [
      aws_dynamodb_table.anomalies.arn,
      "${aws_dynamodb_table.anomalies.arn}/index/*",
    ]
  }

  statement {
    sid    = "WindowsRead"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.price_windows.arn]
  }
}

resource "aws_iam_policy" "api_handler_dynamodb" {
  name   = "tickwatch-api-handler-dynamodb-${var.environment}"
  policy = data.aws_iam_policy_document.api_handler_dynamodb.json
}

resource "aws_iam_role_policy_attachment" "api_handler_dynamodb" {
  role       = aws_iam_role.lambda_api_handler.name
  policy_arn = aws_iam_policy.api_handler_dynamodb.arn
}
