# Adopts the Aurora cluster, its writer and the app user's secret that scripts/deployment/create-aurora-express.ps1
# made (data.tf explains why). Once imported, these blocks do
# nothing. On a rebuild after terraform destroy, run that script again before terraform apply.

# The secret's ARN ends in a random suffix Secrets Manager adds, so it is looked up by name.
data "aws_secretsmanager_secret" "database_created" {
  name = "${local.prefix}/database"
}

import {
  to = aws_secretsmanager_secret.database
  id = data.aws_secretsmanager_secret.database_created.arn
}

import {
  to = aws_rds_cluster.main
  id = local.prefix
}

import {
  to = aws_rds_cluster_instance.main
  id = "${local.prefix}-instance-1"
}
