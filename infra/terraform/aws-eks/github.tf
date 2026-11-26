# GitHub Actions deploys to this cluster (.github/workflows/deploy-eks.yml; docs/deployment/eks-cicd.md) with a role
# it assumes through OIDC: no AWS key is stored in GitHub. Only a run in the repository's "aws-production"
# environment may assume it, and that environment asks a person to approve each run.
#
# The role may: push images to the telesales-* repositories, read the overlay parameter below, and open the
# cluster's API to the runner's address for the length of a run (eks:UpdateClusterConfig: the endpoint is otherwise
# open to cluster_admin_cidrs only). Inside the cluster it is an admin (an access entry): a release applies
# cluster-scoped objects too (NodePools, the EFS volume).

variable "github_repository" {
  type        = string
  default     = ""
  description = "owner/name of the GitHub repository whose deploy workflow may assume the role. Empty: no role."
}

variable "create_github_oidc_provider" {
  type        = bool
  default     = true
  description = "false when the account already has the token.actions.githubusercontent.com provider (one per account)."
}

locals {
  github_enabled = var.github_repository != ""
  github_oidc_arn = (var.create_github_oidc_provider
    ? one(aws_iam_openid_connect_provider.github[*].arn)
  : "arn:${local.partition}:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com")
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = local.github_enabled && var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_deploy" {
  count = local.github_enabled ? 1 : 0
  name  = "${local.prefix}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:aws-production"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  count = local.github_enabled ? 1 : 0
  name  = "deploy"
  role  = aws_iam_role.github_deploy[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload", "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload", "ecr:ListImages", "ecr:PutImage", "ecr:UploadLayerPart",
        ]
        Resource = "arn:${local.partition}:ecr:${var.region}:${local.account_id}:repository/telesales-*"
      },
      {
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster", "eks:UpdateClusterConfig", "eks:DescribeUpdate", "eks:ListUpdates"]
        Resource = module.eks.cluster_arn
      },
      { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = aws_ssm_parameter.overlay.arn },
    ]
  })
}

resource "aws_eks_access_entry" "github_deploy" {
  count         = local.github_enabled ? 1 : 0
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.github_deploy[0].arn
}

resource "aws_eks_access_policy_association" "github_deploy" {
  count         = local.github_enabled ? 1 : 0
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.github_deploy[0].arn
  policy_arn    = "arn:${local.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
  depends_on = [aws_eks_access_entry.github_deploy]
}

# What the workflow renders the manifests with (outputs.tf, local.overlay), plus the registry and the cluster's name.
# Endpoints and ARNs only, no secret.
resource "aws_ssm_parameter" "overlay" {
  name  = "/${local.prefix}/overlay"
  type  = "String"
  value = jsonencode(merge(local.overlay, { ecr_registry = local.ecr_registry, cluster = module.eks.cluster_name }))
}

output "github_deploy_role_arn" {
  description = "GitHub repository variable AWS_EKS_DEPLOY_ROLE_ARN (docs/deployment/eks-cicd.md)."
  value       = one(aws_iam_role.github_deploy[*].arn)
}
