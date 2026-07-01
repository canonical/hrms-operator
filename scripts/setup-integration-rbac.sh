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
# This script applies a RoleBinding that covers all service accounts in the
# "testing" model namespace (created by juju add-model testing before this
# script runs).

set -euo pipefail

MODEL_NAMESPACE="testing"

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
kind: RoleBinding
metadata:
  name: juju-secret-consumer-patch-secrets
  namespace: ${MODEL_NAMESPACE}
subjects:
- kind: Group
  name: system:serviceaccounts:${MODEL_NAMESPACE}
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: juju-secret-consumer-patch-secrets
  apiGroup: rbac.authorization.k8s.io
EOF

echo "RBAC applied: juju-secret-consumer service accounts can now patch secrets in ${MODEL_NAMESPACE}"
