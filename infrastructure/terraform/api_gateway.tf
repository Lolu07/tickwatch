# ---------------------------------------------------------------------------
# HTTP API Gateway v2 — serves the React dashboard.
#
# HTTP API (v2) vs REST API (v1):
#   HTTP API is ~70% cheaper, has native CORS support, and lower latency.
#   REST API adds features like request validation, caching, and usage plans
#   that we don't need here. Use HTTP API for simple Lambda-backed APIs.
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "dashboard" {
  name          = "tickwatch-api-${var.environment}"
  protocol_type = "HTTP"
  description   = "TickWatch anomaly dashboard API"

  # CORS: allow the Vite dev server and any hosted origin.
  # In prod, restrict allow_origins to your actual domain.
  cors_configuration {
    allow_headers = ["Content-Type", "Authorization"]
    allow_methods = ["GET", "OPTIONS"]
    allow_origins = var.environment == "prod" ? [var.frontend_origin] : ["*"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.dashboard.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_logs.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      durationMs     = "$context.responseLatency"
      ip             = "$context.identity.sourceIp"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/aws/apigateway/tickwatch-${var.environment}"
  retention_in_days = 7
}

# ---------------------------------------------------------------------------
# Lambda integration — proxy all routes to the API Lambda
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_integration" "api_lambda" {
  api_id                 = aws_apigatewayv2_api.dashboard.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_handler.invoke_arn
  payload_format_version = "2.0"   # required for HTTP API v2 event format
}

resource "aws_apigatewayv2_route" "get_anomalies" {
  api_id    = aws_apigatewayv2_api.dashboard.id
  route_key = "GET /anomalies"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

resource "aws_apigatewayv2_route" "get_anomalies_symbol" {
  api_id    = aws_apigatewayv2_api.dashboard.id
  route_key = "GET /anomalies/{symbol}"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

resource "aws_apigatewayv2_route" "get_window" {
  api_id    = aws_apigatewayv2_api.dashboard.id
  route_key = "GET /windows/{symbol}"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

resource "aws_apigatewayv2_route" "get_symbols" {
  api_id    = aws_apigatewayv2_api.dashboard.id
  route_key = "GET /symbols"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

# Allow API Gateway to invoke the Lambda
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.dashboard.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# API Lambda function
# ---------------------------------------------------------------------------

data "archive_file" "api_lambda_package" {
  type        = "zip"
  source_dir  = "${path.root}/../../lambda/api_handler"
  output_path = "${path.module}/api_lambda_package.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

resource "aws_lambda_function" "api_handler" {
  function_name    = "tickwatch-api-handler-${var.environment}"
  role             = aws_iam_role.lambda_api_handler.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.api_lambda_package.output_path
  source_code_hash = data.archive_file.api_lambda_package.output_base64sha256
  timeout          = 15
  memory_size      = 128

  environment {
    variables = {
      ANOMALY_TABLE = aws_dynamodb_table.anomalies.name
      WINDOW_TABLE  = aws_dynamodb_table.price_windows.name
      SYMBOLS       = "AAPL,MSFT,GOOGL,AMZN,TSLA,META,NVDA,SPY"
      LOG_LEVEL     = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.api_handler_logs]
}

resource "aws_cloudwatch_log_group" "api_handler_logs" {
  name              = "/aws/lambda/tickwatch-api-handler-${var.environment}"
  retention_in_days = 7
}
