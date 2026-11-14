# --- RDS PostgreSQL 16 ---------------------------------------------------------------------------------------
# Single-AZ, automated backups and point-in-time recovery. The master password is RDS-managed in Secrets Manager:
# it never enters this state. The runtime role (telesales_runtime) and the app_db_eval database are made once by
# hand (docs/deployment/aws-terraform-cicd.md, step 4).
resource "aws_db_subnet_group" "main" {
  name       = local.prefix
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "main" {
  name   = "${local.prefix}-pg16"
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "main" {
  identifier                      = local.prefix
  engine                          = "postgres"
  engine_version                  = "16"
  instance_class                  = var.db_instance_class
  allocated_storage               = var.db_allocated_storage_gb
  max_allocated_storage           = var.db_max_allocated_storage_gb
  storage_type                    = "gp3"
  storage_encrypted               = true
  db_name                         = "app_db"
  username                        = "telesales_admin"
  manage_master_user_password     = true
  db_subnet_group_name            = aws_db_subnet_group.main.name
  vpc_security_group_ids          = [aws_security_group.db.id]
  parameter_group_name            = aws_db_parameter_group.main.name
  multi_az                        = var.db_multi_az
  publicly_accessible             = false
  backup_retention_period         = var.db_backup_retention_days
  backup_window                   = "18:00-19:00" # 01:00-02:00 in Viet Nam, before the weekly round
  maintenance_window              = "sun:19:30-sun:20:30"
  copy_tags_to_snapshot           = true
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.prefix}-final"
  performance_insights_enabled    = true
  auto_minor_version_upgrade      = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
  apply_immediately               = false
}

# --- EFS: the agent's shared files ---------------------------------------------------------------------------
# skills/ (Reflection's versions, active.json), improvement/ (gaps, signals, reviews), kb/ (knowledge versions),
# runs/ (the weekly round's evaluation runs and lessons, between its learn and measure tasks).
# Pay per GB stored: no fixed cost.
resource "aws_efs_file_system" "main" {
  creation_token   = local.prefix
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  tags = { Name = local.prefix }
}

resource "aws_efs_mount_target" "main" {
  count           = length(aws_subnet.public)
  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = aws_subnet.public[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_backup_policy" "main" {
  file_system_id = aws_efs_file_system.main.id
  backup_policy {
    status = "ENABLED"
  }
}

# --- Container images ----------------------------------------------------------------------------------------

locals {
  # Repository names: docs/deployment/README.md section 2, plus asr and the weekly round.
  repositories = ["backend-common", "gateway", "commerce", "identity", "sales", "ai-agent", "web", "asr", "improve"]
}

resource "aws_ecr_repository" "main" {
  for_each = toset(local.repositories)
  # Fixed names: the compose files and the workflows refer to telesales-<image>.
  name                 = "telesales-${each.key}"
  image_tag_mutability = "IMMUTABLE_WITH_EXCLUSION"
  # The Fargate tasks run <repo>:latest-release, the one tag each release moves (a task cannot override its image).
  image_tag_mutability_exclusion_filter {
    filter      = var.release_alias_tag
    filter_type = "WILDCARD"
  }
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "main" {
  for_each   = aws_ecr_repository.main
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 30 releases"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
      action       = { type = "expire" }
    }]
  })
}

# --- Releases and secrets ------------------------------------------------------------------------------------

# Each release's compose files (s3://.../releases/<sha>/), which new instances download at boot.
resource "aws_s3_bucket" "releases" {
  bucket = "${local.prefix}-releases-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "releases" {
  bucket                  = aws_s3_bucket.releases.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "releases" {
  bucket = aws_s3_bucket.releases.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "releases" {
  bucket = aws_s3_bucket.releases.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "releases" {
  bucket = aws_s3_bucket.releases.id
  rule {
    id     = "old-releases"
    status = "Enabled"
    filter {
      prefix = "releases/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# The release every instance runs. The deploy workflow writes it, then refreshes the instances.
resource "aws_ssm_parameter" "release" {
  name  = "/${var.name}/${var.environment}/release"
  type  = "String"
  value = "none"
  lifecycle {
    ignore_changes = [value]
  }
}

# The application's secrets as one JSON object (keys: docs/deployment/aws-plan.md section 5). Terraform makes the
# container only: the values are put by a person (aws secretsmanager put-secret-value) and never enter the state.
resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name}/${var.environment}/app"
  description             = "Application secrets (JSON). Values are set by hand, not by Terraform."
  recovery_window_in_days = 30
}

# What the deploy workflow needs to know, in one place, so GitHub holds only the role ARN and the region.
resource "aws_ssm_parameter" "deploy" {
  name = "/${var.name}/${var.environment}/deploy"
  type = "String"
  value = jsonencode({
    region            = var.region
    domain            = var.domain
    ecr_registry      = local.ecr_registry
    release_bucket    = aws_s3_bucket.releases.bucket
    release_parameter = aws_ssm_parameter.release.name
    asg_name          = aws_autoscaling_group.app.name
    cluster           = aws_ecs_cluster.main.name
    ops_task          = aws_ecs_task_definition.ops.family
    subnets           = aws_subnet.public[*].id
    task_sg           = aws_security_group.task.id
    release_alias     = var.release_alias_tag
    target_groups     = [aws_lb_target_group.web.arn, aws_lb_target_group.gateway.arn]
  })
}
