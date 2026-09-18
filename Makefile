.PHONY: setup teardown status verify-sandbox agent-kubeconfig install smoke-test eval eval-one

# Creates the kind cluster and installs the full target stack (OTel Demo +
# Loki + RBAC sandbox + NodePort services). Safe to re-run.
setup:
	bash setup/create-cluster.sh
	bash setup/install-stack.sh
	bash setup/generate-agent-kubeconfig.sh

# Refresh the rca-agent ServiceAccount token (it's short-lived; re-run this
# if tools start failing with 401/token-expired after several hours).
agent-kubeconfig:
	bash setup/generate-agent-kubeconfig.sh

# Create/refresh the Python virtualenv and install project dependencies.
install:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]" || .venv/Scripts/pip install -e ".[dev]"

# Live-tests every tool module against the running cluster (not mocks).
# Run after any change to src/tools/*.py or the cluster setup.
smoke-test:
	.venv/bin/python tests/smoke_test_live.py || .venv/Scripts/python tests/smoke_test_live.py

# Deletes the kind cluster entirely.
teardown:
	kind delete cluster --name rca-agent

# Quick health check: cluster, pods, and reachability of each backend.
status:
	@echo "=== kind clusters ==="
	@kind get clusters
	@echo ""
	@echo "=== pods in otel-demo ==="
	@kubectl get pods -n otel-demo
	@echo ""
	@echo "=== NodePort services ==="
	@kubectl get svc -n otel-demo -o wide | grep -i nodeport || true

# Proves the RBAC sandbox boundary holds (see setup/rbac/).
verify-sandbox:
	bash setup/verify-sandbox.sh

# Run the full evaluation harness (all 5 core scenarios, inject/agent/score/teardown).
# Results are written to eval/results/.
eval:
	.venv/bin/python -m eval.runner --output-dir eval/results || .venv/Scripts/python -m eval.runner --output-dir eval/results

# Run a single scenario evaluation, e.g.: make eval-one SCENARIO=payment_failure
eval-one:
	.venv/bin/python -m eval.runner --scenario $(SCENARIO) --output-dir eval/results || .venv/Scripts/python -m eval.runner --scenario $(SCENARIO) --output-dir eval/results
