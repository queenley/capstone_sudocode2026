variable "name" {
  type        = string
  default     = "telesales"
  description = "Prefix of every resource name."
}

variable "environment" {
  type    = string
  default = "production"
}

variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "domain" {
  type        = string
  description = "Public name of the shop, e.g. shop.example.com. The ALB serves it with an ACM certificate."
}

variable "hosted_zone_id" {
  type        = string
  default     = ""
  description = "Route 53 zone of the domain. Empty: add the certificate's validation record and the ALB alias at your DNS by hand (outputs)."
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

# --- Compute -------------------------------------------------------------------------------------------------

variable "instance_type" {
  type        = string
  default     = "r7i.large"
  description = "2 vCPU / 16 GB: the agent holds up to 3 GB and mostly waits on the model. An assumption to measure."
}

variable "asg_min" {
  type    = number
  default = 2
}

variable "asg_max" {
  type    = number
  default = 4
}

variable "root_volume_gb" {
  type    = number
  default = 60
}

variable "health_check_grace_seconds" {
  type        = number
  default     = 1200
  description = "The agent loads its MCP servers and embedding model before it is ready: minutes, not seconds."
}

variable "health_check_type" {
  type        = string
  default     = "ELB"
  description = "ELB replaces an instance whose app is unhealthy. EC2 only for the first bootstrap, before any release exists (docs/deployment/aws-terraform-cicd.md, step 2)."
  validation {
    condition     = contains(["ELB", "EC2"], var.health_check_type)
    error_message = "ELB or EC2."
  }
}

variable "docker_compose_version" {
  type    = string
  default = "v2.34.0"
}

# --- Data ----------------------------------------------------------------------------------------------------

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 50
}

variable "db_max_allocated_storage_gb" {
  type    = number
  default = 200
}

variable "db_multi_az" {
  type        = bool
  default     = false
  description = "Single-AZ with backups and PITR by default (aws-plan.md 3.1). true doubles the instance price."
}

variable "db_backup_retention_days" {
  type    = number
  default = 7
}

# --- Weekly improvement round --------------------------------------------------------------------------------

variable "improve_schedule_enabled" {
  type        = bool
  default     = false
  description = "Spends model calls every week. Turn on once the improve image is pushed and the secret has OPENAI_API_KEY and EVAL_DATABASE_URL."
}

variable "release_alias_tag" {
  type        = string
  default     = "latest-release"
  description = "The one mutable tag in ECR: the deploy workflow moves it to each release, and the Fargate tasks (ops, improve) run it."
}

variable "eval_budget_db" {
  type        = string
  default     = ""
  description = "Path, on EFS (/opt/telesales/evaluation/runs/...), of an evaluation budget ledger; empty: no spending cap."
}

# --- Operations ----------------------------------------------------------------------------------------------

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alarm_email" {
  type        = string
  default     = ""
  description = "Receives alarms and the budget warning; empty: alarms go to the SNS topic only."
}

variable "monthly_budget_usd" {
  type        = number
  default     = 300
  description = "AWS spend warning (model API spend is the provider's, not AWS's)."
}

# --- GitHub Actions ------------------------------------------------------------------------------------------

variable "github_repository" {
  type        = string
  description = "owner/name of the repository whose workflows may assume the deploy and Terraform roles."
}

variable "create_github_oidc_provider" {
  type        = bool
  default     = true
  description = "false when the account already has token.actions.githubusercontent.com (one per account)."
}

variable "tf_state_bucket" {
  type        = string
  description = "S3 bucket holding this state (backend.hcl); the plan role reads and locks it."
}
