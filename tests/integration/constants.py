# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared constants for the Frappe HRMS integration tests."""

MARIADB_APP = "mariadb-k8s"
REDIS_APP = "redis-k8s"
FRAPPE_APP = "frappe-hrms"
GATEWAY_APP = "gateway-api-integrator"
INGRESS_CONFIGURATOR_APP = "ingress-configurator"
CERTIFICATES_APP = "self-signed-certificates"

GATEWAY_CLASS = "cilium"
EXTERNAL_HOSTNAME = "hrms.internal"

PROMETHEUS_APP = "prometheus-k8s"
LOKI_APP = "loki-k8s"
GRAFANA_APP = "grafana-k8s"
