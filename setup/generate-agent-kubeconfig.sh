#!/usr/bin/env bash
# Generates a standalone kubeconfig authenticating as the sandboxed rca-agent
# ServiceAccount (not your cluster-admin identity). The agent -- and anyone
# testing its tools -- should always run against this, so that testing
# actually exercises the RBAC boundary in setup/rbac/ instead of silently
# running with full cluster-admin power.
#
# Token is short-lived (--duration below); re-run this script to refresh it.
set -euo pipefail

CLUSTER_NAME="kind-rca-agent"
NAMESPACE="otel-demo"
SA="rca-agent"
DURATION="${1:-24h}"
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/kubeconfig-agent.yaml"

SERVER=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name==\"$CLUSTER_NAME\")].cluster.server}")
CA_DATA=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name==\"$CLUSTER_NAME\")].cluster.certificate-authority-data}")
TOKEN=$(kubectl create token "$SA" -n "$NAMESPACE" --duration="$DURATION")

cat > "$OUT" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: $CLUSTER_NAME
    cluster:
      server: $SERVER
      certificate-authority-data: $CA_DATA
users:
  - name: $SA
    user:
      token: $TOKEN
contexts:
  - name: $SA@$CLUSTER_NAME
    context:
      cluster: $CLUSTER_NAME
      namespace: $NAMESPACE
      user: $SA
current-context: $SA@$CLUSTER_NAME
EOF

echo "Wrote $OUT (token valid for $DURATION)"
echo "Set KUBECONFIG=$OUT in .env to use it, or: export KUBECONFIG=$OUT"
