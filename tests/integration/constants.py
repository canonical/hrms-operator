# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared constants for the Frappe HRMS integration tests."""

MARIADB_APP = "mariadb-k8s"
VALKEY_APP = "valkey"
FRAPPE_APP = "frappe-hrms"
GATEWAY_APP = "gateway-api-integrator"
INGRESS_CONFIGURATOR_APP = "ingress-configurator"
CERTIFICATES_APP = "self-signed-certificates"

GATEWAY_CLASS = "cilium"
EXTERNAL_HOSTNAME = "hrms.internal"

CHARM_NAME = "hrms"
CHARMHUB_CHANNEL = "16/edge"
DEPLOY_TIMEOUT = 10 * 60
UPGRADE_TIMEOUT = 10 * 60
