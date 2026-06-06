terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Store state in S3 so the team shares a single source of truth.
  # Create the bucket manually before first `terraform init`.
  backend "s3" {
    bucket = "tickwatch-terraform-state"
    key    = "streaming/terraform.tfstate"
    region = "us-east-1"
    # Enable server-side encryption at rest
    encrypt = true
    # Enable state locking via DynamoDB (prevents concurrent applies)
    dynamodb_table = "tickwatch-terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "TickWatch"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
