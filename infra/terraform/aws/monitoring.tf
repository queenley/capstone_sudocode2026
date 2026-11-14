# The minimum alarms of aws-plan.md section 6, to one SNS topic (and an email when alarm_email is set).
resource "aws_sns_topic" "alarms" {
  name = "${local.prefix}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email # confirm the subscription from the email AWS sends
}

locals {
  alb_dimension = { LoadBalancer = aws_lb.main.arn_suffix }
  alarms = {
    alb-5xx = {
      namespace = "AWS/ApplicationELB", metric = "HTTPCode_ELB_5XX_Count", statistic = "Sum", threshold = 10,
      period    = 300, periods = 1, dimensions = local.alb_dimension, description = "The ALB answered 5xx (no healthy target, timeouts)."
    }
    target-5xx = {
      namespace = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", statistic = "Sum", threshold = 20,
      period    = 300, periods = 1, dimensions = local.alb_dimension, description = "The application answered 5xx."
    }
    # Many 429 from the gateway's rate limit: spam or a bot. The signal to consider WAF (aws-plan.md 3.1).
    target-4xx = {
      namespace = "AWS/ApplicationELB", metric = "HTTPCode_Target_4XX_Count", statistic = "Sum", threshold = 2000,
      period    = 300, periods = 2, dimensions = local.alb_dimension, description = "Unusual 4xx volume (rate limit 429, scans)."
    }
    slow = {
      namespace = "AWS/ApplicationELB", metric = "TargetResponseTime", statistic = "p95", threshold = 10,
      period    = 300, periods = 3, dimensions = local.alb_dimension, description = "p95 response time over 10 s (SSE streams excluded only if short)."
    }
    gateway-unhealthy = {
      namespace  = "AWS/ApplicationELB", metric = "UnHealthyHostCount", statistic = "Maximum", threshold = 0,
      period     = 300, periods = 3, description = "A gateway target stayed unhealthy for 15 minutes.",
      dimensions = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.gateway.arn_suffix }
    }
    rds-cpu = {
      namespace = "AWS/RDS", metric = "CPUUtilization", statistic = "Average", threshold = 80,
      period    = 300, periods = 3, dimensions = { DBInstanceIdentifier = aws_db_instance.main.identifier }, description = "RDS CPU over 80% for 15 minutes."
    }
    rds-storage = {
      namespace = "AWS/RDS", metric = "FreeStorageSpace", statistic = "Minimum", threshold = 5 * 1024 * 1024 * 1024, comparison = "LessThanThreshold",
      period    = 300, periods = 1, dimensions = { DBInstanceIdentifier = aws_db_instance.main.identifier }, description = "RDS has under 5 GB free."
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "main" {
  for_each            = local.alarms
  alarm_name          = "${local.prefix}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = can(regex("^p[0-9]", each.value.statistic)) ? null : each.value.statistic
  extended_statistic  = can(regex("^p[0-9]", each.value.statistic)) ? each.value.statistic : null
  period              = each.value.period
  evaluation_periods  = each.value.periods
  threshold           = each.value.threshold
  comparison_operator = lookup(each.value, "comparison", "GreaterThanThreshold")
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# A Fargate task (migration, seed, weekly round) that stopped with a non-zero exit code.
resource "aws_cloudwatch_event_rule" "task_failed" {
  name        = "${local.prefix}-task-failed"
  description = "An ops or improve task exited with an error"
  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.main.arn]
      lastStatus = ["STOPPED"]
      containers = { exitCode = [{ "anything-but" = 0 }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "task_failed" {
  rule = aws_cloudwatch_event_rule.task_failed.name
  arn  = aws_sns_topic.alarms.arn
}

data "aws_iam_policy_document" "alarms_topic" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com", "cloudwatch.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.alarms_topic.json
}

# AWS spend only; the model provider's spend needs its own limit at the provider.
resource "aws_budgets_budget" "monthly" {
  name         = "${local.prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.alarm_email == "" ? [] : [80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value == 100 ? "FORECASTED" : "ACTUAL"
      subscriber_email_addresses = [var.alarm_email]
    }
  }
}
