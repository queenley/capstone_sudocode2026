# AWS on EKS (docs/deployment/eks-architecture.md): VPC over three AZs, EKS with Karpenter, Aurora PostgreSQL
# Serverless v2, ElastiCache Serverless (Valkey), EFS, SQS, ECR, Pod Identity, and the cluster add-ons (AWS Load
# Balancer Controller, External Secrets, KEDA, metrics-server, Karpenter, EFS CSI). The manifests that run on it are
# infra/kubernetes/overlays/aws-production.
#
# A separate root from infra/terraform/aws (the EC2 + Docker Compose stack): the two never share state.
#
#   terraform init -backend-config=backend.hcl
#   terraform apply -target=module.vpc -target=module.eks      # the cluster first: the helm provider needs it
#   terraform apply
#
# Spends money while it exists (section 5): about 120-150 USD a month with nodes at zero and Aurora paused.
terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.0"
    }
  }

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
data "aws_availability_zones" "available" {
  state = "available"
  # Regular AZs only: an account opted into a Local Zone (ap-southeast-1-han-1a, Hanoi) would get it here, and EKS's
  # control plane, NAT gateways and RDS subnet groups refuse Local Zones.
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  partition    = data.aws_partition.current.partition
  prefix       = "${var.name}-${var.environment}"
  cluster_name = local.prefix
  ecr_registry = "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com"
  azs          = slice(data.aws_availability_zones.available.names, 0, 3)
  namespace    = "telesales-production"
}
