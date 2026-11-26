# The after-call queue (apps/ai-agent-service/src/ai_agent_service/runtime/jobs.py, ai_agent_service.worker):
# hanging up sends one message; the worker runs after_call (MemoryAgent, QaAgent) and deletes it. The API may only
# send, the worker only receive and delete (identity.tf: their Pod Identity roles).
#
# Retries: a message whose job could not run comes back after the visibility timeout and goes to the dead-letter
# queue after maxReceiveCount receives. The database remains the record: the worker's one-minute sweep also
# finishes every ended call still marked pending, so a dead letter means the worker itself kept failing.

resource "aws_sqs_queue" "after_call_dlq" {
  name                      = "${local.prefix}-after-call-dlq"
  message_retention_seconds = 1209600 # 14 days, to read what failed
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "after_call" {
  name = "${local.prefix}-after-call"
  # Longer than one after_call (two model calls and the ledger writes; harness.remember holds a 5-minute lease).
  visibility_timeout_seconds = 300
  message_retention_seconds  = 345600 # 4 days: the sweep only reaches back 2 days
  receive_wait_time_seconds  = 20     # long polling: an idle worker costs one request per 20 s
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.after_call_dlq.arn
    maxReceiveCount     = 5
  })
}

# ai-agent-service: send only.
resource "aws_iam_policy" "jobs_send" {
  name = "${local.prefix}-after-call-send"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.after_call.arn }]
  })
}

# ai-agent-worker: receive and delete; KEDA's scaler reads the queue's length with GetQueueAttributes.
resource "aws_iam_policy" "jobs_consume" {
  name = "${local.prefix}-after-call-consume"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
      Resource = aws_sqs_queue.after_call.arn
    }]
  })
}

# KEDA's operator: the queue's length only, for the worker's SQS scaler (identity.tf, keda_identity).
resource "aws_iam_policy" "jobs_read_length" {
  name = "${local.prefix}-after-call-length"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["sqs:GetQueueAttributes"], Resource = aws_sqs_queue.after_call.arn }]
  })
}

# A message reached the dead-letter queue: the worker failed on it five times.
resource "aws_cloudwatch_metric_alarm" "after_call_dead_letters" {
  alarm_name          = "${local.prefix}-after-call-dead-letters"
  alarm_description   = "after_call jobs in the dead-letter queue: read them (aws sqs receive-message) and the worker's logs."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.after_call_dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# The oldest message has waited over 10 minutes: no worker is reading (KEDA, the node pool) or it is too slow.
resource "aws_cloudwatch_metric_alarm" "after_call_backlog" {
  alarm_name          = "${local.prefix}-after-call-backlog"
  alarm_description   = "after_call jobs waiting over 10 minutes: check the ai-agent-worker pods and their KEDA ScaledObject."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.after_call.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 600
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}
