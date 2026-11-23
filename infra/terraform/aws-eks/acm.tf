# The shop's TLS certificate for the ALB (overlays/aws-production/ingress.yaml), unless var.certificate_arn names one
# that exists. ACM validates by DNS:
# - domain.tf registered the domain, or route53_zone_id is set: Terraform writes the validation record and waits until the certificate is issued;
# - empty (DNS elsewhere): Terraform requests the certificate and prints the record to add by hand
#   (output certificate_validation_records); the Ingress gets no HTTPS listener until ACM has issued it.
# The record pointing the domain at the ALB is not here: the Load Balancer Controller makes the ALB
# (docs/deployment/eks-deploy.md, section 2.8).

locals {
  request_certificate = var.certificate_arn == ""
  validate_in_route53 = local.request_certificate && local.dns_in_route53
}

resource "aws_acm_certificate" "shop" {
  count             = local.request_certificate ? 1 : 0
  domain_name       = var.domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = local.validate_in_route53 ? {
    for option in flatten(aws_acm_certificate.shop[*].domain_validation_options) : option.domain_name => option
  } : {}

  zone_id         = local.zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 300
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "shop" {
  count                   = local.validate_in_route53 ? 1 : 0
  certificate_arn         = aws_acm_certificate.shop[0].arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}

locals {
  # Through the validation when Terraform waits for it, so nothing uses the certificate before it is issued.
  certificate_arn = coalesce(
    var.certificate_arn,
    one(aws_acm_certificate_validation.shop[*].certificate_arn),
    one(aws_acm_certificate.shop[*].arn),
  )
}
