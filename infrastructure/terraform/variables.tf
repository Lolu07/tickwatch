variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment — used in resource names and tags"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod"
  }
}

variable "stream_name" {
  description = "Name of the Kinesis Data Stream"
  type        = string
  default     = "tickwatch-trades"
}

variable "shard_count" {
  description = <<-EOT
    Number of shards. Each shard handles 1 MB/s write and 2 MB/s read.
    For the 8 symbols in the default config, 1 shard is sufficient in dev.
    Scale to ~1 shard per 5 high-volume symbols in prod.
  EOT
  type        = number
  default     = 1
}

variable "retention_period_hours" {
  description = "How long Kinesis retains records (24–8760 hours). 24h is free; longer costs extra."
  type        = number
  default     = 24

  validation {
    condition     = var.retention_period_hours >= 24 && var.retention_period_hours <= 8760
    error_message = "retention_period_hours must be between 24 and 8760"
  }
}

variable "ingestion_service_role_name" {
  description = "Name of the IAM role assumed by the ingestion service (ECS task / EC2 instance profile)"
  type        = string
  default     = "tickwatch-ingestion-role"
}

variable "frontend_origin" {
  description = "Allowed CORS origin in prod (e.g. https://tickwatch.example.com). Ignored in dev."
  type        = string
  default     = "https://tickwatch.example.com"
}
