# Makes the Aurora cluster an AWS Free plan account allows (express configuration), which Terraform cannot create
# (infra/terraform/aws-eks/data.tf explains why), then the app's role and database inside it.
# Run after the VPC and EKS exist and before the full terraform apply, which imports what this made
# (aurora-import.tf). Safe to run again: each step skips what is already there. Prints no secret.
#
#   pwsh scripts/deployment/create-aurora-express.ps1
#
# Steps:
#   1. Secrets Manager secret telesales-production/database: {"username": "telesales", "password": <generated>}.
#   2. Aurora cluster, express configuration, in the VPC's database subnets behind the data security group. Its
#      master user (cluster_admin) signs in with IAM only; express allows neither a password nor an RDS-managed one.
#   3. A one-off pod on a system node signs in as cluster_admin with an IAM token and creates the role telesales
#      (password from step 1) and the database app_db it owns. DATABASE_URL (overlays/aws-production/secrets.yaml)
#      uses that role.
param(
    [string]$Region = "ap-southeast-1",
    [string]$Prefix = "telesales-production"
)
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$secretName = "$Prefix/database"

# 1. The app role's password
$existing = aws secretsmanager list-secrets --region $Region --filters "Key=name,Values=$secretName" --query "SecretList[?Name=='$secretName'].ARN" --output text
if (-not $existing) {
    $chars = [char[]]"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    $password = -join (1..40 | ForEach-Object { $chars[[System.Security.Cryptography.RandomNumberGenerator]::GetInt32($chars.Length)] })
    $body = @{ username = "telesales"; password = $password } | ConvertTo-Json -Compress
    $file = New-TemporaryFile
    try {
        Set-Content -Path $file -Value $body -NoNewline -Encoding utf8NoBOM
        aws secretsmanager create-secret --region $Region --name $secretName `
            --description "Aurora app user (express configuration: RDS cannot manage it). infra/terraform/aws-eks/data.tf" `
            --secret-string "file://$file" --query ARN --output text | Out-Null
    } finally { Remove-Item $file -Force }
    Remove-Variable password, body
    Write-Host "secret $secretName created"
} else { Write-Host "secret $secretName exists" }

# 2. The cluster
$status = aws rds describe-db-clusters --region $Region --query "DBClusters[?DBClusterIdentifier=='$Prefix'].Status" --output text
if (-not $status) {
    # The data security group and the database subnet group, both from terraform apply -target=module.vpc (network.tf)
    $sg = aws ec2 describe-security-groups --region $Region --filters "Name=group-name,Values=$Prefix-data" --query "SecurityGroups[0].GroupId" --output text
    if (-not $sg -or $sg -eq "None") { throw "no security group $Prefix-data: apply the VPC first (eks-deploy.md 2.2)" }
    aws rds create-db-cluster --region $Region --db-cluster-identifier $Prefix --engine aurora-postgresql `
        --with-express-configuration --enable-vpc-networking --no-enable-internet-access-gateway `
        --db-subnet-group-name $Prefix --vpc-security-group-ids $sg --master-username cluster_admin `
        --query "DBCluster.Status" --output text | Out-Null
    Write-Host "cluster $Prefix creating (about 10 minutes)"
}
aws rds wait db-cluster-available --region $Region --db-cluster-identifier $Prefix
$endpoint = aws rds describe-db-clusters --region $Region --db-cluster-identifier $Prefix --query "DBClusters[0].Endpoint" --output text
Write-Host "cluster available: $endpoint"

# 3. Role telesales and database app_db
$token = aws rds generate-db-auth-token --region $Region --hostname $endpoint --port 5432 --username cluster_admin
$appPassword = (aws secretsmanager get-secret-value --region $Region --secret-id $secretName --query SecretString --output text | ConvertFrom-Json).password
$sql = @'
cat <<SQL | psql "host=$EP port=5432 dbname=postgres user=cluster_admin sslmode=require connect_timeout=90" -v ON_ERROR_STOP=1 -f -
DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'telesales') THEN CREATE ROLE telesales LOGIN; END IF; END \$\$;
ALTER ROLE telesales WITH LOGIN PASSWORD '$APP_PW';
GRANT telesales TO cluster_admin;
SELECT 'CREATE DATABASE app_db OWNER telesales' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'app_db')\gexec
SELECT datname, pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname = 'app_db';
SQL
'@
$pod = @{
    apiVersion = "v1"; kind = "Pod"
    metadata   = @{ name = "aurora-setup"; namespace = "default" }
    spec       = @{
        restartPolicy = "Never"
        tolerations   = @(@{ key = "CriticalAddonsOnly"; operator = "Exists"; effect = "NoSchedule" })
        nodeSelector  = @{ "telesales/pool" = "system" }
        containers    = @(@{
                name = "psql"; image = "postgres:17-alpine"; command = @("sh", "-c", $sql)
                env  = @(@{ name = "PGPASSWORD"; value = $token }, @{ name = "APP_PW"; value = $appPassword }, @{ name = "EP"; value = $endpoint })
            })
    }
}
Remove-Variable token, appPassword
kubectl delete pod aurora-setup -n default --ignore-not-found --wait=true | Out-Null
$pod | ConvertTo-Json -Depth 10 | kubectl apply -f - | Out-Null
Remove-Variable pod
try {
    $deadline = (Get-Date).AddMinutes(5)
    do {
        $phase = kubectl get pod aurora-setup -n default -o jsonpath='{.status.phase}'
        if ($phase -in "Succeeded", "Failed") { break }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    kubectl logs aurora-setup -n default
    if ($phase -ne "Succeeded") { throw "aurora-setup ended $phase (log above)" }
} finally {
    kubectl delete pod aurora-setup -n default --ignore-not-found | Out-Null  # it held the password and the token
}
Write-Host "done: role telesales owns app_db. Next: terraform apply in infra/terraform/aws-eks (imports the cluster)."
