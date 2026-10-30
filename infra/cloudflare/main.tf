terraform {
  required_version = ">= 1.5.0"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

variable "cloudflare_account_id" {
  description = "Cloudflare Account ID owning congressional-tech-raw R2 bucket"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare Zone ID for spicygov.ai"
  type        = string
}

locals {
  edge_config    = jsondecode(file("${path.module}/congressional-data-r2-edge.json"))
  transform_spec = local.edge_config.response_header_transform_rules[0]
}

resource "cloudflare_r2_bucket_cors" "public_r2_cors" {
  account_id  = var.cloudflare_account_id
  bucket_name = local.edge_config.custom_domain.bucket

  dynamic "rules" {
    for_each = local.edge_config.cors.rules
    content {
      id = rules.value.id
      allowed {
        origins = rules.value.allowed.origins
        methods = rules.value.allowed.methods
        headers = rules.value.allowed.headers
      }
      expose_headers  = rules.value.expose_headers
      max_age_seconds = rules.value.max_age_seconds
    }
  }
}

resource "cloudflare_ruleset" "public_r2_response_headers" {
  zone_id     = var.cloudflare_zone_id
  name        = local.transform_spec.ruleset.name
  description = local.transform_spec.description
  kind        = local.transform_spec.ruleset.kind
  phase       = local.transform_spec.ruleset.phase

  dynamic "rules" {
    for_each = local.transform_spec.ruleset.rules
    content {
      ref         = rules.value.ref
      description = rules.value.description
      expression  = rules.value.expression
      action      = rules.value.action
      enabled     = rules.value.enabled

      action_parameters {
        dynamic "headers" {
          for_each = rules.value.action_parameters.headers
          content {
            name       = headers.key
            operation  = headers.value.operation
            value      = lookup(headers.value, "value", null)
            expression = lookup(headers.value, "expression", null)
          }
        }
      }
    }
  }
}
