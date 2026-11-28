# Each workload's AWS rights, through EKS Pod Identity: a role per service account, nothing on the nodes.
# The service accounts are the manifests' (overlays/aws-production).

module "lb_controller_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                            = "${local.prefix}-aws-lb-controller"
  use_name_prefix                 = false # the prefix form exceeds IAM's 38 characters for name_prefix
  attach_aws_lb_controller_policy = true
  associations = {
    main = { cluster_name = module.eks.cluster_name, namespace = "kube-system", service_account = "aws-load-balancer-controller" }
  }
}

module "efs_csi_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                      = "${local.prefix}-efs-csi"
  attach_aws_efs_csi_policy = true
}

# External Secrets reads the one app secret and the database's managed password, nothing else.
module "external_secrets_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                                  = "${local.prefix}-external-secrets"
  attach_external_secrets_policy        = true
  external_secrets_secrets_manager_arns = [aws_secretsmanager_secret.app.arn, aws_secretsmanager_secret.database.arn]
  external_secrets_create_permission    = false
  associations = {
    main = { cluster_name = module.eks.cluster_name, namespace = "external-secrets", service_account = "external-secrets" }
  }
}

# ai-agent-service: send to the after-call queue (runtime/jobs.py).
module "agent_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                   = "${local.prefix}-ai-agent-service"
  additional_policy_arns = { send = aws_iam_policy.jobs_send.arn }
  associations = {
    main = { cluster_name = module.eks.cluster_name, namespace = local.namespace, service_account = "ai-agent-service" }
  }
}

# ai-agent-worker: receive and delete.
module "worker_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                   = "${local.prefix}-ai-agent-worker"
  additional_policy_arns = { consume = aws_iam_policy.jobs_consume.arn }
  associations = {
    main = { cluster_name = module.eks.cluster_name, namespace = local.namespace, service_account = "ai-agent-worker" }
  }
}

# KEDA's operator reads the queue's length for the worker's scaler (TriggerAuthentication identityOwner: keda,
# overlays/aws-production). identityOwner: workload would look for an IRSA annotation on the worker's service
# account, which Pod Identity does not set.
module "keda_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                   = "${local.prefix}-keda"
  additional_policy_arns = { length = aws_iam_policy.jobs_read_length.arn }
  associations = {
    main = { cluster_name = module.eks.cluster_name, namespace = "keda", service_account = "keda-operator" }
  }
}

# Where the queue alarms go (queue.tf).
resource "aws_sns_topic" "alarms" {
  name = "${local.prefix}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}
