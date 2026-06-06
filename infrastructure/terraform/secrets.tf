# ---------------------------------------------------------------------------
# Secrets Manager — Claude API key for anomaly explanations (Phase 5)
#
# The secret *value* is NOT managed by Terraform to keep the key out of
# Terraform state. After `terraform apply`, populate it once:
#
#   aws secretsmanager put-secret-value \
#     --secret-id "$(terraform output -raw claude_secret_name)" \
#     --secret-string "sk-ant-..."
#
# The Lambda reads it at cold start via boto3; the key is never written to
# environment variables (which appear in plaintext in the Lambda console).
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "claude_api_key" {
  name        = "tickwatch/claude-api-key-${var.environment}"
  description = "Anthropic Claude API key for TickWatch anomaly explanations"

  # 7-day recovery window lets you restore an accidentally deleted secret.
  # Set to 0 for immediate deletion in CI/ephemeral environments.
  recovery_window_in_days = 7
}
