# ECS is used only for one-shot Fargate tasks, billed while they run:
# - "ops": migrations and the catalog seed, once per release (the deploy workflow overrides the command);
# - "improve": the weekly improvement round (infra/improve), on two EventBridge schedules, in place of Airflow.
resource "aws_ecs_cluster" "main" {
  name = local.prefix
}

resource "aws_cloudwatch_log_group" "tasks" {
  for_each          = toset(["ops", "improve"])
  name              = "/${var.name}/${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Pulls the image, reads the secret into the container's environment, writes the logs.
resource "aws_iam_role" "task_execution" {
  name               = "${local.prefix}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secret" {
  name = "app-secret"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "secretsmanager:GetSecretValue", Resource = aws_secretsmanager_secret.app.arn }]
  })
}

# What the code in the task may do: mount EFS. Nothing else in AWS.
resource "aws_iam_role" "task" {
  name               = "${local.prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "task_efs" {
  name = "efs"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
      Resource = aws_efs_file_system.main.arn
    }]
  })
}

locals {
  # Keys of the app secret (JSON) a task gets as environment variables.
  ops_secrets     = ["DATABASE_URL", "MIGRATION_DATABASE_URL", "APP_SECRET", "ENCRYPTION_KEY", "ADMIN_TOKEN", "AGENT_TOKEN", "SELLER_TOKEN", "DEVELOPER_TOKEN"]
  improve_secrets = ["DATABASE_URL", "EVAL_DATABASE_URL", "APP_SECRET", "OPENAI_API_KEY"]
  # The improve image keeps the repository's layout (infra/improve/Dockerfile).
  improve_mounts = {
    skills      = "/opt/telesales/apps/ai-agent-service/data/skills"
    improvement = "/opt/telesales/apps/ai-agent-service/data/improvement"
    kb          = "/opt/telesales/apps/ai-agent-service/data/kb"
    runs        = "/opt/telesales/evaluation/runs"
  }
}

resource "aws_ecs_task_definition" "ops" {
  family                   = "${local.prefix}-ops"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name      = "ops"
    image     = "${local.ecr_registry}/telesales-backend-common:${var.release_alias_tag}"
    essential = true
    # The migration of infra/kubernetes/migrate-job.yaml; the deploy workflow also runs the seed with this task.
    command     = ["python", "-c", "import os; from src.db.session import Database; Database(os.environ['MIGRATION_DATABASE_URL']).migrate()"]
    environment = [{ name = "ENVIRONMENT", value = "production" }]
    secrets     = [for key in local.ops_secrets : { name = key, valueFrom = "${aws_secretsmanager_secret.app.arn}:${key}::" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.tasks["ops"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "ops"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "improve" {
  family                   = "${local.prefix}-improve"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 2048
  memory                   = 8192
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  dynamic "volume" {
    for_each = local.improve_mounts
    content {
      name = volume.key
      efs_volume_configuration {
        file_system_id     = aws_efs_file_system.main.id
        root_directory     = "/${volume.key}" # made by the instances' user data
        transit_encryption = "ENABLED"
        authorization_config {
          iam = "ENABLED"
        }
      }
    }
  }

  container_definitions = jsonencode([{
    name        = "improve"
    image       = "${local.ecr_registry}/telesales-improve:${var.release_alias_tag}"
    essential   = true
    command     = ["tick"]
    environment = concat([{ name = "AGENT_DB_SCHEMA", value = "agent" }], var.eval_budget_db == "" ? [] : [{ name = "EVAL_BUDGET_DB", value = var.eval_budget_db }])
    secrets     = [for key in local.improve_secrets : { name = key, valueFrom = "${aws_secretsmanager_secret.app.arn}:${key}::" }]
    mountPoints = [for name, path in local.improve_mounts : { sourceVolume = name, containerPath = path, readOnly = false }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.tasks["improve"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "improve"
      }
    }
  }])
}

# --- The weekly round's two schedules (aws-plan.md 3.7) ------------------------------------------------------

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name = "run-improve"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "ecs:RunTask"
        Resource  = "${aws_ecs_task_definition.improve.arn_without_revision}:*"
        Condition = { ArnLike = { "ecs:cluster" = aws_ecs_cluster.main.arn } }
      },
      { Effect = "Allow", Action = "iam:PassRole", Resource = [aws_iam_role.task_execution.arn, aws_iam_role.task.arn] },
    ]
  })
}

locals {
  schedules = {
    # Monday 02:00 in Viet Nam: restate the gaps, R0, learn, proposals for the admin.
    learn = { expression = "cron(0 2 ? * MON *)", command = ["learn"] }
    # Three times a day, never earlier than 8 hours after the learn task starts (it may run up to 6): expire an
    # overdue round, or measure one whose proposals are all decided. Doing nothing is the common case.
    tick = { expression = "cron(0 10,16,22 ? * * *)", command = ["tick"] }
  }
}

resource "aws_scheduler_schedule" "improve" {
  for_each                     = local.schedules
  name                         = "${local.prefix}-improve-${each.key}"
  state                        = var.improve_schedule_enabled ? "ENABLED" : "DISABLED"
  schedule_expression          = each.value.expression
  schedule_expression_timezone = "Asia/Ho_Chi_Minh"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      containerOverrides = [{ name = "improve", command = each.value.command }]
    })

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.improve.arn_without_revision
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = aws_subnet.public[*].id
        security_groups  = [aws_security_group.task.id]
        assign_public_ip = true # no NAT: the task reaches the model APIs through its public address
      }
    }

    retry_policy {
      maximum_retry_attempts = 0 # a learn run spends money: a failure is looked at, not retried blindly
    }
  }
}
