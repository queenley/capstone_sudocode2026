# What infra/kubernetes/overlays/aws-production needs; scripts/deployment/render_deployment.py fills it in.
# The same values are in SSM for the deploy workflow (github.tf).
locals {
  overlay = {
    region              = var.region
    domain              = var.domain
    certificate_arn     = local.certificate_arn
    jobs_queue_url      = aws_sqs_queue.after_call.url
    jobs_queue_name     = aws_sqs_queue.after_call.name
    valkey_endpoint     = aws_elasticache_serverless_cache.main.endpoint[0].address
    valkey_port         = aws_elasticache_serverless_cache.main.endpoint[0].port
    database_endpoint   = aws_rds_cluster.main.endpoint
    database_secret_arn = aws_secretsmanager_secret.database.arn
    app_secret_name     = aws_secretsmanager_secret.app.name
    efs_id              = aws_efs_file_system.main.id
    efs_access_point    = aws_efs_access_point.agent.id
    karpenter_node_role = module.karpenter.node_iam_role_name
    langfuse_host       = var.langfuse_host
  }
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "update_kubeconfig" {
  description = "Run to reach the cluster from an address in cluster_admin_cidrs."
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

output "ecr_registry" {
  value = local.ecr_registry
}

output "overlay" {
  description = "The values of overlays/aws-production: render_deployment.py --env aws-production --terraform-output <this>."
  value       = local.overlay
}

output "dead_letter_queue_url" {
  value = aws_sqs_queue.after_call_dlq.url
}

output "certificate_validation_records" {
  description = "Only when Terraform requested the certificate and no Route 53 zone holds the domain: add these at the DNS provider; the certificate is issued a few minutes later."
  value = var.certificate_arn == "" && !local.dns_in_route53 ? [
    for option in flatten(aws_acm_certificate.shop[*].domain_validation_options) :
    { name = option.resource_record_name, type = option.resource_record_type, value = option.resource_record_value }
  ] : []
}

output "name_servers" {
  description = "Set these four at the registrar of var.domain (the hosted zone made by domain.tf); HTTPS waits for them."
  value       = flatten(aws_route53_zone.shop[*].name_servers)
}
