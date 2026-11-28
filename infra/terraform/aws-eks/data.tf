# The data tier, private subnets only, reachable from the nodes only (network.tf).

# ── Aurora PostgreSQL Serverless v2 ─────────────────────────
# One cluster, one database app_db, the services' schemas inside it, as on EC2.
#
# On the AWS Free plan, RDS creates an Aurora cluster only "with express configuration", which the AWS provider
# cannot request (no such argument in aws_rds_cluster). So the cluster is made once with the AWS CLI and adopted
# here by aurora-import.tf (scripts/deployment/create-aurora-express.ps1). Express sets its own values: one
# writer, 0-4 ACU, 1 day of backups, no storage encryption, and a master user (cluster_admin) that signs in with
# IAM only. Terraform therefore only reads it (ignore_changes = all); change it with aws rds modify-db-cluster.
#
# The app signs in as telesales, an ordinary role that owns app_db, with the password in the secret below. The
# secret's value is set with the AWS CLI, never through Terraform, so it is not in the state.
resource "aws_secretsmanager_secret" "database" {
  name        = "${local.prefix}/database"
  description = "Aurora app user (express configuration: RDS cannot manage it). infra/terraform/aws-eks/data.tf"
}

resource "aws_rds_cluster" "main" {
  cluster_identifier                  = local.prefix
  engine                              = "aurora-postgresql"
  engine_mode                         = "provisioned"
  master_username                     = "cluster_admin"
  iam_database_authentication_enabled = true
  db_subnet_group_name                = module.vpc.database_subnet_group_name
  vpc_security_group_ids              = [aws_security_group.data.id]
  skip_final_snapshot                 = true # destroy: snapshot first by hand if the data matters

  serverlessv2_scaling_configuration {
    min_capacity = 0
    max_capacity = 4 # the Free plan's ceiling
  }

  lifecycle {
    ignore_changes = all
  }
}

resource "aws_rds_cluster_instance" "main" {
  identifier         = "${local.prefix}-instance-1" # the writer express creates
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine

  lifecycle {
    ignore_changes = all
  }
}

# ── ElastiCache Serverless, Valkey ────────────────────────────
# The gateway's rate limit (REDIS_URL), the shared model limiter, the load signal, the spend ledger and kb:changed
# (AGENT_REDIS_URL), the OTP limits. TLS only: the URLs are rediss://.
resource "aws_elasticache_serverless_cache" "main" {
  engine               = "valkey"
  name                 = local.prefix
  major_engine_version = "8"
  subnet_ids           = module.vpc.private_subnets
  security_group_ids   = [aws_security_group.data.id]

  cache_usage_limits {
    data_storage {
      maximum = 5
      unit    = "GB"
    }
    ecpu_per_second {
      maximum = 5000
    }
  }
}

# ── EFS: skills, improvement state and knowledge versions shared by every agent pod ─────
resource "aws_efs_file_system" "main" {
  creation_token  = local.prefix
  encrypted       = true
  throughput_mode = "elastic"
  tags            = { Name = local.prefix }
}

resource "aws_efs_mount_target" "main" {
  count           = length(module.vpc.private_subnets)
  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = module.vpc.private_subnets[count.index]
  security_groups = [aws_security_group.data.id]
}

# The agent runs as uid 1000 (runAsUser in the manifests): one access point, owned by it.
resource "aws_efs_access_point" "agent" {
  file_system_id = aws_efs_file_system.main.id
  posix_user {
    uid = 1000
    gid = 1000
  }
  root_directory {
    path = "/agent"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0750"
    }
  }
}

# ── ECR ───────────────────────────────────────────────────────────────────
locals {
  images = ["telesales-web", "telesales-gateway", "telesales-backend-common", "telesales-commerce", "telesales-identity",
  "telesales-sales", "telesales-ai-agent", "telesales-asr", "telesales-improve"]
}

resource "aws_ecr_repository" "main" {
  for_each             = var.create_ecr ? toset(local.images) : toset([])
  name                 = each.value
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

# ── the app's secrets (keys, tokens, DATABASE_URL), read by External Secrets ─────────
# Terraform makes the empty secret; its values are set once by hand, never in state.
resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.prefix}/app"
  recovery_window_in_days = 7
}
