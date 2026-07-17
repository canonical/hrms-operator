# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

output "application" {
  description = "Name of the deployed application."
  value       = juju_application.hrms.name
}

output "requires" {
  description = "Map of the requires endpoints consumed by the charm."
  value = {
    ingress = "ingress"
  }
}
