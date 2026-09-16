#!/usr/bin/env bash
# Installs the full target environment into the kind cluster created by
# create-cluster.sh: namespace + RBAC sandbox, the OpenTelemetry Astronomy
# Shop (with agent/chatbot/mcp/opensearch trimmed out, see
# helm-values/otel-demo.yaml), Loki for log storage, and NodePort Services
# for the observability backends. Idempotent -- safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="otel-demo"

echo "==> Adding/updating Helm repos"
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo update >/dev/null

echo "==> Creating namespace + RBAC sandbox"
kubectl apply -f "$SCRIPT_DIR/rbac/namespace.yaml"
kubectl apply -f "$SCRIPT_DIR/rbac/serviceaccount.yaml"
kubectl apply -f "$SCRIPT_DIR/rbac/role.yaml"
kubectl apply -f "$SCRIPT_DIR/rbac/rolebinding.yaml"
kubectl apply -f "$SCRIPT_DIR/rbac/clusterrole-nodes.yaml"
kubectl apply -f "$SCRIPT_DIR/rbac/clusterrolebinding-nodes.yaml"

echo "==> Installing Loki (log storage)"
helm upgrade --install loki grafana/loki \
  --namespace "$NAMESPACE" \
  -f "$SCRIPT_DIR/helm-values/loki.yaml" \
  --wait --timeout 5m

echo "==> Installing OpenTelemetry Astronomy Shop"
helm upgrade --install otel-demo open-telemetry/opentelemetry-demo \
  --namespace "$NAMESPACE" \
  -f "$SCRIPT_DIR/helm-values/otel-demo.yaml"

echo "==> Exposing observability backends via NodePort"
kubectl apply -f "$SCRIPT_DIR/manifests/nodeports.yaml"

echo "==> Waiting for deployments to become Available (this can take several minutes on"
echo "    first run while images are pulled -- Kafka and the .NET/Java services are slowest)"
kubectl wait --for=condition=Available deployment --all -n "$NAMESPACE" --timeout=600s || {
  echo ""
  echo "!! Not all deployments became Available within the timeout. Current status:"
  kubectl get pods -n "$NAMESPACE"
  echo ""
  echo "This is often fine on first install (image pulls still in progress.)"
  echo "Re-run 'kubectl get pods -n $NAMESPACE' to check, or re-run this script."
  exit 1
}

echo ""
echo "==> Stack is up. Access points (once pods are Ready):"
echo "    Shop UI      http://localhost:30800"
echo "    Grafana      http://localhost:30080"
echo "    Prometheus   http://localhost:30090"
echo "    Jaeger UI    http://localhost:30686/jaeger/ui"
echo "    flagd-ui     http://localhost:30800/feature (via frontend-proxy)"
echo ""
kubectl get pods -n "$NAMESPACE"
