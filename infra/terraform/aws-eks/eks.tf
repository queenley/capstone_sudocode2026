# The cluster: a small on-demand node group for the add-ons and Karpenter, which then adds nodes for the app
# (overlays/aws-cluster/karpenter.yaml: on-demand for ai-agent-service, general for the rest). Access through EKS
# access entries (the creator is admin); each workload's AWS rights through Pod Identity (identity.tf).
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = local.cluster_name
  kubernetes_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.cluster_admin_cidrs

  enable_cluster_creator_admin_permissions = true

  addons = {
    coredns                = {}
    kube-proxy             = {}
    vpc-cni                = { before_compute = true }
    eks-pod-identity-agent = { before_compute = true }
    aws-efs-csi-driver = {
      pod_identity_association = [{
        role_arn        = module.efs_csi_identity.iam_role_arn
        service_account = "efs-csi-controller-sa"
      }]
    }
  }

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = var.system_instance_types
      min_size       = 2
      max_size       = 3
      desired_size   = 2
      labels         = { "telesales/pool" = "system" }
      # Only what tolerates this runs here: the add-ons and Karpenter; the app goes to Karpenter's nodes.
      taints = {
        system = { key = "CriticalAddonsOnly", value = "true", effect = "NO_SCHEDULE" }
      }
    }
  }

  node_security_group_tags = {
    "karpenter.sh/discovery" = local.cluster_name
  }
}

# Karpenter's controller role (Pod Identity), its node role, and the interruption queue for Spot notices.
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 21.0"

  cluster_name                    = module.eks.cluster_name
  namespace                       = "kube-system"
  create_pod_identity_association = true
  enable_inline_policy            = true # the controller policy exceeds a managed policy's 6,144 characters
  node_iam_role_use_name_prefix   = false
  node_iam_role_name              = "${local.prefix}-karpenter-node"
  node_iam_role_additional_policies = {
    ssm = "arn:${local.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
}
