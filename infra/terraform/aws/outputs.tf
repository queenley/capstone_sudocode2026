output "alb_dns_name" {
  description = "Point the domain at it (CNAME, or Route 53 alias) when hosted_zone_id is empty."
  value       = aws_lb.main.dns_name
}

output "certificate_validation_records" {
  description = "Without hosted_zone_id: create these at your DNS, or apply waits for them."
  value = {
    for option in aws_acm_certificate.main.domain_validation_options :
    option.domain_name => { name = option.resource_record_name, type = option.resource_record_type, value = option.resource_record_value }
  }
}

output "app_secret_arn" {
  description = "Put the application's secrets here as one JSON object (docs/deployment/aws-terraform-cicd.md, step 3)."
  value       = aws_secretsmanager_secret.app.arn
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

output "rds_master_secret_arn" {
  description = "The RDS-managed master password, to create the runtime role and app_db_eval once."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}

output "ecr_registry" {
  value = local.ecr_registry
}

output "deploy_parameter" {
  description = "SSM parameter the deploy workflow reads (registry, bucket, group, cluster, subnets...)."
  value       = aws_ssm_parameter.deploy.name
}

output "github_roles" {
  description = "Set as GitHub variables: AWS_DEPLOY_ROLE_ARN, AWS_TERRAFORM_PLAN_ROLE_ARN, AWS_TERRAFORM_APPLY_ROLE_ARN."
  value = {
    AWS_DEPLOY_ROLE_ARN          = aws_iam_role.deploy.arn
    AWS_TERRAFORM_PLAN_ROLE_ARN  = aws_iam_role.terraform_plan.arn
    AWS_TERRAFORM_APPLY_ROLE_ARN = aws_iam_role.terraform_apply.arn
  }
}

output "asg_name" {
  value = aws_autoscaling_group.app.name
}

output "efs_id" {
  value = aws_efs_file_system.main.id
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
