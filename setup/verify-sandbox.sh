#!/usr/bin/env bash
# Proves the RBAC sandbox boundary from setup/rbac/ actually holds, using
# `kubectl auth can-i --as` impersonation of the rca-agent ServiceAccount --
# no need to mint a real token just to check this. Exits non-zero if any
# check disagrees with its expected answer, so it can double as a CI gate.
set -uo pipefail

SA="system:serviceaccount:otel-demo:rca-agent"
FAILURES=0

check() {
  local expect="$1" verb="$2" resource="$3" ns_flag="$4" label="$5"
  local got
  if [ -n "$ns_flag" ]; then
    got=$(kubectl auth can-i "$verb" "$resource" -n "$ns_flag" --as="$SA" 2>/dev/null)
  else
    got=$(kubectl auth can-i "$verb" "$resource" --as="$SA" 2>/dev/null)
  fi
  if [ "$got" = "$expect" ]; then
    echo "OK    [$label] expected '$expect', got '$got'"
  else
    echo "FAIL  [$label] expected '$expect', got '$got'"
    FAILURES=$((FAILURES + 1))
  fi
}

echo "Testing sandbox boundary as $SA"
echo ""
check yes get    pods              otel-demo   "read pods in otel-demo"
check yes get    pods/log          otel-demo   "read pod logs in otel-demo"
check yes get    nodes             ""          "read nodes (cluster-scoped)"
check no  delete pods              otel-demo   "delete pods in otel-demo"
check no  create pods/exec         otel-demo   "exec into pods"
check no  get    secrets           otel-demo   "read secrets"
check no  get    pods              kube-system "read pods outside otel-demo"
check no  delete nodes             ""          "delete a node"
check no  create deployments       otel-demo   "create/modify workloads"

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "All sandbox boundary checks passed."
else
  echo "$FAILURES check(s) FAILED -- the sandbox does not match its intended design."
  exit 1
fi
