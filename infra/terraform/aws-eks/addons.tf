# The cluster add-ons the manifests rely on (section 6, item 2), as Helm releases. The helm provider talks to the
# cluster this root creates: apply the cluster first (versions.tf). Chart versions are pinned; Karpenter's must
# match kubernetes_version, so it is a variable.

data "aws_eks_cluster_auth" "main" {
  name = module.eks.cluster_name
}

provider "helm" {
  # Every chart names its repository URL, so this machine's own `helm repo add` list is not needed; a repo there
  # with no cached index (helm repo list) would fail every release with "no cached repo found".
  repository_config_path = "${path.module}/.terraform/helm/repositories.yaml"
  repository_cache       = "${path.module}/.terraform/helm/cache"

  kubernetes = {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    token                  = data.aws_eks_cluster_auth.main.token
  }
}

locals {
  # The add-ons run on the system node group, which only tolerating pods may use (eks.tf).
  system_tolerations = [{ key = "CriticalAddonsOnly", operator = "Exists", effect = "NoSchedule" }]
}

resource "helm_release" "karpenter" {
  name       = "karpenter"
  namespace  = "kube-system"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = var.karpenter_version
  wait       = true
  # The controller crashes without its IAM policy, and its Service needs the LB controller's webhook (below).
  depends_on = [module.karpenter, helm_release.aws_load_balancer_controller]

  values = [yamlencode({
    settings = {
      clusterName       = module.eks.cluster_name
      clusterEndpoint   = module.eks.cluster_endpoint
      interruptionQueue = module.karpenter.queue_name
    }
    serviceAccount = { name = module.karpenter.service_account }
    tolerations    = local.system_tolerations
    nodeSelector   = { "telesales/pool" = "system" }
  })]
}

resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = "3.6.2"
  wait       = true # its webhook mutates every Service: the releases below create Services, so they wait for it

  values = [yamlencode({
    clusterName    = module.eks.cluster_name
    region         = var.region
    vpcId          = module.vpc.vpc_id
    serviceAccount = { name = "aws-load-balancer-controller" }
    tolerations    = local.system_tolerations
  })]
}

resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = "2.14.0"
  depends_on       = [helm_release.aws_load_balancer_controller]

  values = [yamlencode({
    serviceAccount = { name = "external-secrets" }
    tolerations    = local.system_tolerations
    # The chart's webhook and cert controller take their own tolerations; without them they stay Pending.
    webhook        = { tolerations = local.system_tolerations }
    certController = { tolerations = local.system_tolerations }
  })]
}

resource "helm_release" "keda" {
  name             = "keda"
  namespace        = "keda"
  create_namespace = true
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = "2.21.0"
  depends_on       = [helm_release.aws_load_balancer_controller]

  values = [yamlencode({
    # The SQS scaler assumes the worker's own role (TriggerAuthentication identityOwner: workload).
    podIdentity = { aws = { irsa = { enabled = false } } }
    tolerations = local.system_tolerations
  })]
}

resource "helm_release" "metrics_server" {
  name       = "metrics-server"
  namespace  = "kube-system"
  repository = "https://kubernetes-sigs.github.io/metrics-server/"
  chart      = "metrics-server"
  version    = "3.14.0"
  depends_on = [helm_release.aws_load_balancer_controller]

  values = [yamlencode({ tolerations = local.system_tolerations })]
}
