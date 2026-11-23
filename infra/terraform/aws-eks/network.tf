# Three AZs: public subnets for the ALB and the NAT, private ones for the nodes, the database, Valkey and EFS.
# Karpenter finds the private subnets and the node security group by their karpenter.sh/discovery tag.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  name = local.prefix
  cidr = var.vpc_cidr
  azs  = local.azs

  private_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets   = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 48 + i)]
  database_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 64 + i)]

  enable_nat_gateway     = var.nat_gateway
  single_nat_gateway     = var.single_nat_gateway
  one_nat_gateway_per_az = !var.single_nat_gateway

  create_database_subnet_group = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
    "karpenter.sh/discovery"          = local.cluster_name
  }
}

# The data tier answers the cluster's nodes only.
resource "aws_security_group" "data" {
  name        = "${local.prefix}-data"
  description = "Aurora, Valkey and EFS: from the EKS nodes only"
  vpc_id      = module.vpc.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "data" {
  for_each = {
    postgres = 5432
    valkey   = 6379
    efs      = 2049
  }
  security_group_id            = aws_security_group.data.id
  referenced_security_group_id = module.eks.node_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
  description                  = each.key
}
