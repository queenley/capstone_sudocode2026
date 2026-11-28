# A monthly cost budget that emails alarm_email before the bill gets out of hand. On 2026-11-27 the account, on the
# Free plan, used up its credits with nobody warned and AWS closed it: the site, DNS and keys stopped together
# (docs/deployment/eks-deploy.md, section 5). A budget warns; it never stops a resource. Two budgets per account
# are free. Without alarm_email there is nobody to warn, so no budget is made.
resource "aws_budgets_budget" "monthly" {
  count        = var.alarm_email == "" ? 0 : 1
  name         = "${local.prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Spent so far passes half, then all of the budget.
  dynamic "notification" {
    for_each = [50, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alarm_email]
    }
  }

  # The month is on course to pass 80%: the earliest warning, while there is still time to shut down.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alarm_email]
  }
}
