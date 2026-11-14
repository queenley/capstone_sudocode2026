# GitHub Actions reach AWS by OIDC: no long-lived access key anywhere. Three roles, each trusted for one kind of run:
# - deploy:          .github/workflows/deploy-aws.yml, in the "aws-production" environment (a person approves);
# - terraform-plan:  .github/workflows/terraform-aws.yml on a pull request: read-only;
# - terraform-apply: the same workflow's apply job, in the "aws-production" environment.
locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:${local.partition}:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"
  github_subjects = {
    production   = "repo:${var.github_repository}:environment:aws-production"
    pull_request = "repo:${var.github_repository}:pull_request"
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  for_each = local.github_subjects
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [each.value]
    }
  }
}

# --- deploy: build, push, migrate, release -------------------------------------------------------------------

resource "aws_iam_role" "deploy" {
  name                 = "${local.prefix}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_assume["production"].json
  max_session_duration = 7200 # an instance refresh of two instances takes up to an hour
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPush"
    actions = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload", "ecr:DescribeImages",
    "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart"]
    resources = [for repository in aws_ecr_repository.main : repository.arn]
  }
  statement {
    sid       = "Config"
    actions   = ["ssm:GetParameter", "ssm:PutParameter"]
    resources = [aws_ssm_parameter.release.arn, aws_ssm_parameter.deploy.arn]
  }
  statement {
    sid       = "ReleaseFiles"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.releases.arn}/releases/*"]
  }
  statement {
    sid       = "RunOps"
    actions   = ["ecs:RunTask"]
    resources = ["${aws_ecs_task_definition.ops.arn_without_revision}:*"]
    condition {
      test     = "ArnLike"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }
  statement {
    sid       = "WatchOps"
    actions   = ["ecs:DescribeTasks"]
    resources = ["*"]
    condition {
      test     = "ArnLike"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }
  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.task_execution.arn, aws_iam_role.task.arn]
  }
  statement {
    sid       = "OpsLogs"
    actions   = ["logs:GetLogEvents"]
    resources = ["${aws_cloudwatch_log_group.tasks["ops"].arn}:*"]
  }
  statement {
    sid       = "Refresh"
    actions   = ["autoscaling:StartInstanceRefresh", "autoscaling:CancelInstanceRefresh"]
    resources = [aws_autoscaling_group.app.arn]
  }
  statement {
    sid       = "Watch"
    actions   = ["autoscaling:DescribeInstanceRefreshes", "autoscaling:DescribeAutoScalingGroups", "elasticloadbalancing:DescribeTargetHealth"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

# --- Terraform -----------------------------------------------------------------------------------------------

resource "aws_iam_role" "terraform_plan" {
  name               = "${local.prefix}-github-terraform-plan"
  assume_role_policy = data.aws_iam_policy_document.github_assume["pull_request"].json
}

resource "aws_iam_role_policy_attachment" "terraform_plan" {
  role       = aws_iam_role.terraform_plan.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/ReadOnlyAccess"
}

# A plan refreshes the state and takes the lock (a .tflock object beside the state).
resource "aws_iam_role_policy" "terraform_plan_state" {
  name = "state"
  role = aws_iam_role.terraform_plan.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = "arn:${local.partition}:s3:::${var.tf_state_bucket}" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "arn:${local.partition}:s3:::${var.tf_state_bucket}/*" },
    ]
  })
}

# Creates IAM roles, so it is an administrator: only a run a person approved in the aws-production environment gets it.
resource "aws_iam_role" "terraform_apply" {
  name               = "${local.prefix}-github-terraform-apply"
  assume_role_policy = data.aws_iam_policy_document.github_assume["production"].json
}

resource "aws_iam_role_policy_attachment" "terraform_apply" {
  role       = aws_iam_role.terraform_apply.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AdministratorAccess"
}
