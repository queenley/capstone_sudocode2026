# Buys var.domain through Route 53 Domains when register_domain is true (docs/deployment/eks-deploy.md, 2.1):
# one year, paid when this is created and never refunded; auto-renew off. Route 53 makes the domain's hosted zone
# itself; acm.tf validates the certificate in it. The Route 53 Domains API lives in us-east-1 only.
#
# terraform destroy deletes the registration (the rest of the year is lost) and leaves the hosted zone, which
# still costs 0.50 USD a month: delete it by hand (eks-deploy.md, 5.3).

provider "aws" {
  alias  = "domains"
  region = "us-east-1"
}

resource "aws_route53domains_domain" "shop" {
  count    = var.register_domain ? 1 : 0
  provider = aws.domains

  domain_name       = var.domain
  duration_in_years = 1
  auto_renew        = false

  admin_privacy      = true
  registrant_privacy = true
  tech_privacy       = true

  dynamic "registrant_contact" {
    for_each = [var.domain_contact]
    content {
      contact_type   = "PERSON"
      first_name     = registrant_contact.value.first_name
      last_name      = registrant_contact.value.last_name
      email          = registrant_contact.value.email
      phone_number   = registrant_contact.value.phone_number
      address_line_1 = registrant_contact.value.address_line1
      city           = registrant_contact.value.city
      country_code   = registrant_contact.value.country_code
      zip_code       = registrant_contact.value.zip_code
    }
  }
  dynamic "admin_contact" {
    for_each = [var.domain_contact]
    content {
      contact_type   = "PERSON"
      first_name     = admin_contact.value.first_name
      last_name      = admin_contact.value.last_name
      email          = admin_contact.value.email
      phone_number   = admin_contact.value.phone_number
      address_line_1 = admin_contact.value.address_line1
      city           = admin_contact.value.city
      country_code   = admin_contact.value.country_code
      zip_code       = admin_contact.value.zip_code
    }
  }
  dynamic "tech_contact" {
    for_each = [var.domain_contact]
    content {
      contact_type   = "PERSON"
      first_name     = tech_contact.value.first_name
      last_name      = tech_contact.value.last_name
      email          = tech_contact.value.email
      phone_number   = tech_contact.value.phone_number
      address_line_1 = tech_contact.value.address_line1
      city           = tech_contact.value.city
      country_code   = tech_contact.value.country_code
      zip_code       = tech_contact.value.zip_code
    }
  }

  lifecycle {
    precondition {
      condition     = var.domain_contact != null
      error_message = "register_domain needs domain_contact in terraform.tfvars (who registers the domain)."
    }
  }
}

# A domain bought elsewhere (a .vn name from a Vietnamese registrar): its DNS lives in a hosted zone made here, once
# the registrar's name servers are set to output name_servers. terraform destroy deletes it; a new zone gets new
# name servers, which must be set at the registrar again.
resource "aws_route53_zone" "shop" {
  count = !var.register_domain && var.create_hosted_zone && var.route53_zone_id == "" ? 1 : 0
  name  = var.domain
}

locals {
  # Known at plan time (acm.tf's for_each depends on it): whether a Route 53 zone will hold the records.
  dns_in_route53 = var.register_domain || var.route53_zone_id != "" || var.create_hosted_zone
  zone_id = coalesce(
    var.route53_zone_id,
    one(aws_route53domains_domain.shop[*].hosted_zone_id),
    one(aws_route53_zone.shop[*].zone_id),
  )
}
