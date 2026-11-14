# One ALB, the same routes as the one-server Caddyfile (infra/compose/caddy/Caddyfile): /api/* (the API, the Zalo
# webhook, the browser's voice WebSocket) to the gateway, everything else to web. No WAF (aws-plan.md 3.1).
resource "aws_lb" "main" {
  name               = local.prefix
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  # A voice call holds one WebSocket; SSE streams a reply. 60 s (the default) would cut them.
  idle_timeout               = 300
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}

resource "aws_lb_target_group" "web" {
  name                 = "${local.prefix}-web"
  port                 = 3000
  protocol             = "HTTP"
  vpc_id               = aws_vpc.main.id
  target_type          = "instance"
  deregistration_delay = 30
  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 4
  }
}

resource "aws_lb_target_group" "gateway" {
  name        = "${local.prefix}-gateway"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"
  # In-flight SSE replies finish before an instance leaves during an instance refresh.
  deregistration_delay = 120
  health_check {
    # The compose healthcheck: ready when identity, sales and commerce answer.
    path                = "/health/ready"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 4
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.main.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.gateway.arn
  }
  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }
}

# --- Certificate and DNS -------------------------------------------------------------------------------------

resource "aws_acm_certificate" "main" {
  domain_name       = var.domain
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = var.hosted_zone_id == "" ? {} : {
    for option in aws_acm_certificate.main.domain_validation_options : option.domain_name => option
  }
  zone_id         = var.hosted_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 300
  allow_overwrite = true
}

# Without a zone, apply waits here until the record printed by `certificate_validation_records` exists at your DNS.
resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = var.hosted_zone_id == "" ? null : [for record in aws_route53_record.validation : record.fqdn]
  timeouts {
    create = "2h"
  }
}

resource "aws_route53_record" "alias" {
  count   = var.hosted_zone_id == "" ? 0 : 1
  zone_id = var.hosted_zone_id
  name    = var.domain
  type    = "A"
  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}
