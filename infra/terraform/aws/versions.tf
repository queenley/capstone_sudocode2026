# AWS phase 2 (docs/deployment/aws-plan.md, section 3): ALB + an Auto Scaling group of EC2 running Docker Compose,
# RDS PostgreSQL, EFS, ECR, and the weekly improvement round on Fargate. How to apply it and wire GitHub Actions:
# docs/deployment/aws-terraform-cicd.md.
#
# Deliberately absent (aws-plan.md 3.1): EKS, NAT Gateway, interface endpoints, ElastiCache, WAF, MWAA, MSK.
terraform {
  required_version = ">= 1.10.0" # S3 backend with native locking (use_lockfile)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Partial configuration: terraform init -backend-config=backend.hcl (backend.hcl.example).
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  partition    = data.aws_partition.current.partition
  prefix       = "${var.name}-${var.environment}"
  ecr_registry = "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com"
  azs          = slice(data.aws_availability_zones.available.names, 0, 2)
}
