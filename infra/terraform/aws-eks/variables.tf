variable "name" {
  type        = string
  default     = "telesales"
  description = "Prefix of every resource name."
}

variable "environment" {
  type    = string
  default = "production"
}

variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "single_nat_gateway" {
  type        = bool
  default     = true
  description = "One NAT gateway for the three AZs (about 32 USD a month each). false: one per AZ, so losing an AZ does not cut the others off the model APIs."
}

variable "nat_gateway" {
  type        = bool
  default     = true
  description = "false only while the cluster is destroyed: the nodes need the NAT to reach the model APIs, ECR and SQS."
}

variable "kubernetes_version" {
  type    = string
  default = "1.34"
}

variable "cluster_admin_cidrs" {
  type        = list(string)
  description = "Addresses allowed to reach the cluster's public API endpoint (your office, the CI runners). Never 0.0.0.0/0."
  validation {
    condition     = length(var.cluster_admin_cidrs) > 0 && !contains(var.cluster_admin_cidrs, "0.0.0.0/0")
    error_message = "Name the addresses that may reach the API; 0.0.0.0/0 is refused."
  }
}

variable "system_instance_types" {
  type        = list(string)
  default     = ["m7i-flex.large"]
  description = "The small on-demand node group that runs the add-ons and Karpenter itself; Karpenter adds the rest. An AWS Free plan account launches only Free Tier types (aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true): m7i-flex.large (2 vCPU, 8 GiB) is the largest; on a paid plan any type works."
}

variable "karpenter_version" {
  type        = string
  default     = "1.14.3"
  description = "Karpenter's Helm chart. It must support kubernetes_version (karpenter.sh/docs/upgrading/compatibility: Kubernetes 1.34 needs Karpenter 1.6 or later); 1.14 is an LTS line. Raising kubernetes_version: check this first."
}

variable "domain" {
  type        = string
  default     = "quivo.io.vn"
  description = "Public name of the shop; the ALB Ingress serves it with the ACM certificate (acm.tf). Registered by domain.tf when register_domain is true."
}

variable "certificate_arn" {
  type        = string
  default     = ""
  description = "An ACM certificate for var.domain in var.region that already exists. Empty: Terraform requests one (acm.tf)."
}

variable "register_domain" {
  type        = bool
  default     = false
  description = "Buy var.domain through Route 53 Domains (domain.tf): one year, paid at once, not refunded; not for .vn names, and not on a Free plan account. false: the domain is already yours (quivo.io.vn, bought from a Vietnamese registrar)."
}

variable "domain_contact" {
  description = "Registrant of var.domain (register_domain), the same person as admin and tech contact. Personal data: only in terraform.tfvars, never in git. phone_number as +84.912345678; country_code VN. ICANN emails the address once: confirm it within 15 days or the domain is suspended."
  type = object({
    first_name    = string
    last_name     = string
    email         = string
    phone_number  = string
    address_line1 = string
    city          = string
    country_code  = string
    zip_code      = string
  })
  default   = null
  sensitive = true
}

variable "create_hosted_zone" {
  type        = bool
  default     = true
  description = "With register_domain false: make the domain's Route 53 hosted zone here (domain.tf). Then set the registrar's name servers to output name_servers; the certificate validates once they answer."
}

variable "route53_zone_id" {
  type        = string
  default     = ""
  description = "The Route 53 hosted zone of a domain you already own (register_domain = false): Terraform then writes the certificate's validation record itself. Empty, without register_domain (DNS elsewhere): add the records of output certificate_validation_records by hand."
}

variable "create_ecr" {
  type        = bool
  default     = true
  description = "false when infra/terraform/aws already made the repositories in this account and region."
}

variable "langfuse_host" {
  type        = string
  default     = "https://cloud.langfuse.com"
  description = "Where the agent sends its LLM traces; the developer console links each turn there. Keys go in the app secret."
}

variable "alarm_email" {
  type        = string
  default     = ""
  description = "Who hears the queue alarms; empty: create the topic only."
}
