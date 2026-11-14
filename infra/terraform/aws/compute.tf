# EC2 Auto Scaling group: every instance runs the whole compose stack (infra/compose/docker-compose.aws.yml) at the
# release in SSM. Instances keep nothing: state is in RDS and EFS, so a broken instance is replaced, and a release is
# an instance refresh (one instance at a time, the ALB sending traffic only to healthy ones).
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name}/${var.environment}/app"
  retention_in_days = var.log_retention_days
}

# --- Instance role -------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${local.prefix}-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "instance" {
  for_each = {
    ssm = "arn:${local.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore" # Session Manager, Run Command
    ecr = "arn:${local.partition}:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  }
  role       = aws_iam_role.instance.name
  policy_arn = each.value
}

data "aws_iam_policy_document" "instance" {
  statement {
    sid       = "AppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    sid       = "Release"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.release.arn]
  }
  statement {
    sid       = "ReleaseFiles"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.releases.arn}/releases/*"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
  statement {
    sid       = "Efs"
    actions   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
    resources = [aws_efs_file_system.main.arn]
  }
}

resource "aws_iam_role_policy" "instance" {
  name   = "app"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.prefix}-instance"
  role = aws_iam_role.instance.name
}

# --- Launch template and group -------------------------------------------------------------------------------

resource "aws_launch_template" "app" {
  name_prefix            = "${local.prefix}-"
  image_id               = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.app.id]
  update_default_version = true

  iam_instance_profile {
    arn = aws_iam_instance_profile.instance.arn
  }

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1          # containers cannot reach the instance's credentials
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.root_volume_gb
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  user_data = base64encode(templatefile("${path.module}/templates/user_data.sh.tftpl", {
    region            = var.region
    domain            = var.domain
    ecr_registry      = local.ecr_registry
    release_parameter = aws_ssm_parameter.release.name
    release_bucket    = aws_s3_bucket.releases.bucket
    app_secret_arn    = aws_secretsmanager_secret.app.arn
    log_group         = aws_cloudwatch_log_group.app.name
    efs_id            = aws_efs_file_system.main.id
    compose_version   = var.docker_compose_version
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${local.prefix}-app" }
  }
}

resource "aws_autoscaling_group" "app" {
  name                      = "${local.prefix}-app"
  min_size                  = var.asg_min
  max_size                  = var.asg_max
  desired_capacity          = var.asg_min
  vpc_zone_identifier       = aws_subnet.public[*].id
  target_group_arns         = [aws_lb_target_group.web.arn, aws_lb_target_group.gateway.arn]
  health_check_type         = var.health_check_type
  health_check_grace_period = var.health_check_grace_seconds
  default_instance_warmup   = var.health_check_grace_seconds

  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }

  # A changed launch template (AMI, user data, size) is rolled out like a release: one instance at a time.
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = var.health_check_grace_seconds
    }
  }

  # The instances must mount EFS at boot.
  depends_on = [aws_efs_mount_target.main]

  lifecycle {
    ignore_changes = [desired_capacity]
  }
}
