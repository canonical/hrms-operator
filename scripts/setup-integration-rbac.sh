#!/bin/bash
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Apply RBAC to allow Juju secret-consumer service accounts to patch secrets.
#
# Juju creates per-unit service accounts (juju-secret-consumer-<uuid>) in the
# model namespace when a charm grants a Juju secret to another application.
# These accounts need patch/update access to Kubernetes secrets so Juju can
# record the grant. Without this, mariadb-k8s fails in its pebble-ready hook.
#
# This script runs BEFORE "juju add-model testing", so we use a ClusterRoleBinding
# targeting system:serviceaccounts:testing. Kubernetes RBAC evaluates bindings
# lazily — the namespace and service accounts do not need to exist yet.

set -euo pipefail

kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: juju-secret-consumer-patch-secrets
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: juju-secret-consumer-patch-secrets
subjects:
- kind: Group
  name: system:serviceaccounts:testing
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: juju-secret-consumer-patch-secrets
  apiGroup: rbac.authorization.k8s.io
EOF

echo "RBAC applied: juju-secret-consumer service accounts can now patch secrets"
