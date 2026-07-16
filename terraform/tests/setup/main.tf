# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

terraform {
  required_version = "~> 1.12"
  required_providers {
    external = {
      source  = "hashicorp/external"
      version = "> 2"
    }
    juju = {
      version = "~> 2.0"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

variable "channel" {
  description = "The channel to use when deploying the hrms charm."
  type        = string
  default     = "16/edge"
}

variable "revision" {
  description = "Revision number of the hrms charm."
  type        = number
  default     = null
}

variable "database" {
  description = "Minimal MariaDB test input."
  type = object({
    revision = number
  })
}

variable "redis" {
  description = "Minimal Redis test input."
  type = object({
    revision = number
  })
}

resource "juju_model" "test_model" {
  name = "tf-testing-${formatdate("YYYYMMDDhhmmss", timestamp())}"
}

resource "juju_secret" "admin_password" {
  model_uuid = juju_model.test_model.uuid
  name       = "admin-password-secret"
  value = {
    password = "test-admin"
  }
}

module "product" {
  source = "../../product"

  model_uuid = juju_model.test_model.uuid
  channel    = var.channel
  revision   = var.revision
  database = {
    revision = var.database.revision
  }
  redis = {
    revision = var.redis.revision
  }
  config = {
    "admin-password-secret" = juju_secret.admin_password.secret_id
  }

  depends_on = [juju_secret.admin_password]
}

resource "juju_access_secret" "admin_password_access" {
  model_uuid   = juju_model.test_model.uuid
  secret_id    = juju_secret.admin_password.secret_id
  applications = [module.product.application]

  depends_on = [module.product]
}

# tflint-ignore: terraform_unused_declarations
data "external" "app_status" {
  program = ["bash", "${path.module}/../wait-for-active.sh", juju_model.test_model.uuid, module.product.application, "10m"]

  depends_on = [juju_access_secret.admin_password_access]
}

output "model_uuid" {
  value = juju_model.test_model.uuid
}

output "admin_password_secret_id" {
  value = juju_secret.admin_password.secret_id
}

output "application" {
  description = "Name of the deployed application."
  value       = module.product.application
}

output "status" {
  description = "Current application status reported by Juju."
  value       = data.external.app_status.result.status
}
