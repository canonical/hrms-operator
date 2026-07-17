# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "mariadb" {
  name       = var.database.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "mariadb-k8s"
    channel  = var.database.channel
    revision = var.database.revision
    base     = var.database.base
  }

  config      = var.database.config
  constraints = var.database.constraints
  units       = var.database.units
}

resource "juju_application" "redis" {
  name       = var.redis.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "redis-k8s"
    channel  = var.redis.channel
    revision = var.redis.revision
    base     = var.redis.base
  }

  config      = var.redis.config
  constraints = var.redis.constraints
  units       = var.redis.units
}

resource "juju_application" "hrms" {
  name       = var.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "hrms"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  config             = var.config
  constraints        = var.constraints
  units              = var.units
  storage_directives = var.storage
}

resource "juju_integration" "hrms-database" {
  model_uuid = var.model_uuid

  application {
    name     = juju_application.hrms.name
    endpoint = "database"
  }

  application {
    name     = juju_application.mariadb.name
    endpoint = "database"
  }
}

resource "juju_integration" "hrms-redis" {
  model_uuid = var.model_uuid

  application {
    name     = juju_application.hrms.name
    endpoint = "redis"
  }

  application {
    name     = juju_application.redis.name
    endpoint = "redis"
  }
}


