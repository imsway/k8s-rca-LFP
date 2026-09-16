#!/usr/bin/env bash
# Creates the local kind cluster the RCA agent investigates. Idempotent: if
# a cluster named "rca-agent" already exists, this is a no-op.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="rca-agent"

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "kind cluster '$CLUSTER_NAME' already exists, skipping creation."
else
  echo "Creating kind cluster '$CLUSTER_NAME'..."
  kind create cluster --config "$SCRIPT_DIR/kind-config.yaml"
fi

kubectl cluster-info --context "kind-$CLUSTER_NAME"
echo ""
echo "Cluster ready. Nodes:"
kubectl get nodes -o wide
