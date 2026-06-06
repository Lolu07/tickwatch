output "stream_name" {
  description = "Kinesis stream name — set as KINESIS_STREAM_NAME env var in the ingestion service"
  value       = aws_kinesis_stream.trades.name
}

output "stream_arn" {
  description = "Full ARN of the Kinesis stream — used in Lambda event source mapping"
  value       = aws_kinesis_stream.trades.arn
}

output "ingestion_role_arn" {
  description = "IAM role ARN for the ingestion ECS task — set as the ECS task role"
  value       = aws_iam_role.ingestion_task.arn
}

output "ingestion_dev_user_name" {
  description = "IAM user name for local dev (dev environment only)"
  value       = var.environment == "dev" ? aws_iam_user.ingestion_dev[0].name : null
}

output "consumer_policy_arn" {
  description = "ARN of the Kinesis consumer IAM policy — attach to the Phase 3 Lambda role"
  value       = aws_iam_policy.kinesis_consumer.arn
}

output "lambda_function_name" {
  description = "Anomaly detector Lambda function name"
  value       = aws_lambda_function.anomaly_detector.function_name
}

output "lambda_function_arn" {
  description = "Anomaly detector Lambda function ARN"
  value       = aws_lambda_function.anomaly_detector.arn
}

output "window_table_name" {
  description = "DynamoDB table storing rolling price windows"
  value       = aws_dynamodb_table.price_windows.name
}

output "anomaly_table_name" {
  description = "DynamoDB table storing detected anomalies (queried by the dashboard)"
  value       = aws_dynamodb_table.anomalies.name
}

output "lambda_log_group" {
  description = "CloudWatch log group for the anomaly detector — use Logs Insights to query anomalies"
  value       = aws_cloudwatch_log_group.lambda_logs.name
}

output "api_url" {
  description = "Base URL of the HTTP API Gateway — set as VITE_API_URL in dashboard/.env"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "api_handler_function_name" {
  description = "Dashboard API Lambda function name"
  value       = aws_lambda_function.api_handler.function_name
}

output "claude_secret_name" {
  description = "Secrets Manager secret name for the Claude API key — populate after apply: aws secretsmanager put-secret-value --secret-id <value> --secret-string sk-ant-..."
  value       = aws_secretsmanager_secret.claude_api_key.name
}
