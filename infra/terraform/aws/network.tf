# Two AZs, two tiers, no NAT Gateway: instances and Fargate tasks sit in public subnets with public IPv4 and reach
# the model APIs directly; nothing reaches them except through the ALB (security groups). RDS is in private subnets
# that have no route out at all.
data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # EFS mount by DNS name
  tags                 = { Name = local.prefix }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.prefix }
}

resource "aws_subnet" "public" {
  count                   = length(local.azs)
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index)
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.prefix}-public-${local.azs[count.index]}", Tier = "public" }
}

resource "aws_subnet" "private" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + 8)
  tags              = { Name = "${local.prefix}-private-${local.azs[count.index]}", Tier = "private" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${local.prefix}-public" }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private subnets: the VPC's main route table (local routes only).

# Free: S3 traffic (release files, pg_dump) stays off the Internet.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id]
  tags              = { Name = "${local.prefix}-s3" }
}

# --- Security groups -----------------------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${local.prefix}-alb"
  description = "HTTP and HTTPS from the Internet"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.prefix}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb" {
  for_each          = { http = 80, https = 443 }
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = each.value
  to_port           = each.value
  description       = each.key
}

resource "aws_vpc_security_group_egress_rule" "alb" {
  for_each                     = { web = 3000, gateway = 8000 }
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
  description                  = "${each.key} on the instances"
}

resource "aws_security_group" "app" {
  name        = "${local.prefix}-app"
  description = "EC2 running the compose stack: only the ALB gets in; no SSH (SSM Session Manager)"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.prefix}-app" }
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  for_each                     = { web = 3000, gateway = 8000 }
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
  description                  = each.key
}

resource "aws_security_group" "task" {
  name        = "${local.prefix}-task"
  description = "Fargate tasks (migrations, seed, weekly improvement round): outbound only"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.prefix}-task" }
}

# Instances and tasks call the model APIs, ECR, Secrets Manager, SSM and CloudWatch directly.
resource "aws_vpc_security_group_egress_rule" "outbound" {
  for_each          = { app = aws_security_group.app.id, task = aws_security_group.task.id }
  security_group_id = each.value
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "everything out"
}

resource "aws_security_group" "db" {
  name        = "${local.prefix}-db"
  description = "PostgreSQL from the instances and the tasks"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.prefix}-db" }
}

resource "aws_security_group" "efs" {
  name        = "${local.prefix}-efs"
  description = "NFS from the instances and the tasks"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.prefix}-efs" }
}

resource "aws_vpc_security_group_ingress_rule" "db" {
  for_each                     = { app = aws_security_group.app.id, task = aws_security_group.task.id }
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "postgres from ${each.key}"
}

resource "aws_vpc_security_group_ingress_rule" "efs" {
  for_each                     = { app = aws_security_group.app.id, task = aws_security_group.task.id }
  security_group_id            = aws_security_group.efs.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 2049
  to_port                      = 2049
  description                  = "nfs from ${each.key}"
}
