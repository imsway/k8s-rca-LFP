"""Live smoke test for src/tools/* -- NOT a unit test (no mocks). Requires a
running cluster (`make setup`) and a valid kubeconfig-agent.yaml (`bash
setup/generate-agent-kubeconfig.sh`). Run this after any change to the tool
modules or the cluster setup, to confirm every tool still returns real data
and the sandbox/validation checks still hold.

Usage: python tests/smoke_test_live.py
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from src.tools import kubernetes as k8s
from src.tools import loki
from src.tools import prometheus as prom
from src.tools import traces
from src.tools.registry import ALL_TOOLS, audit_log_as_text, clear_audit_log, get_audit_log

NS = "otel-demo"
FAILURES = []


def check(label: str, fn, *args, expect_error: bool = False, **kwargs):
    try:
        result = fn(*args, **kwargs)
        if expect_error:
            print(f"FAIL  {label}: expected an error, got a result")
            FAILURES.append(label)
        else:
            print(f"OK    {label}")
        return result
    except Exception as e:
        if expect_error:
            print(f"OK    {label} (correctly raised {type(e).__name__})")
        else:
            print(f"FAIL  {label}: {type(e).__name__}: {e}")
            FAILURES.append(label)
        return None


print("--- Kubernetes tools ---")
pods = check("get_pod_statuses", k8s.get_pod_statuses, NS)
if pods and pods["pods"]:
    sample_pod = pods["pods"][0]["name"]
    check("get_pod_logs", k8s.get_pod_logs, NS, sample_pod, tail_lines=5)
    check("get_pod_description", k8s.get_pod_description, NS, sample_pod)
check("get_events", k8s.get_events, NS, limit=5)
check("get_deployments", k8s.get_deployments, NS)
check("get_services_and_endpoints", k8s.get_services_and_endpoints, NS)
check("get_configmap (flagd-config)", k8s.get_configmap, NS, "flagd-config")
check("get_nodes", k8s.get_nodes)
check("get_pod_statuses rejects out-of-scope namespace", k8s.get_pod_statuses, "kube-system", expect_error=True)

print("\n--- Prometheus tools ---")
check("query_metric", prom.query_metric, "up")
check("query_metric_range", prom.query_metric_range, "up", lookback_minutes=5)
check("get_firing_alerts", prom.get_firing_alerts)
check("get_scrape_targets", prom.get_scrape_targets)
check("query_metric rejects overlong query", prom.query_metric, "up" * 300, expect_error=True)

print("\n--- Loki tools ---")
check("get_service_names", loki.get_service_names)
check("query_logs", loki.query_logs, '{service_name="cart"}', lookback_minutes=30, limit=5)
check("query_logs rejects bad lookback", loki.query_logs, '{service_name="cart"}',
      lookback_minutes=999, expect_error=True)

print("\n--- Jaeger tools ---")
check("get_services", traces.get_services)
check("get_operations", traces.get_operations, "cart")
trace_result = check("search_traces", traces.search_traces, "cart", limit=3)
if trace_result and trace_result["traces"]:
    check("get_trace_detail", traces.get_trace_detail, trace_result["traces"][0]["trace_id"])
check("get_trace_detail rejects bad trace id", traces.get_trace_detail, "0" * 16, expect_error=True)

print("\n--- Registry (LangChain tool wrapping + audit log) ---")
clear_audit_log()
by_name = {t.name: t for t in ALL_TOOLS}
print(f"OK    {len(ALL_TOOLS)} tools registered")
schema = by_name["get_pod_statuses"].args
if "namespace" in schema and schema["namespace"].get("type") == "string":
    print("OK    tool args schema correctly exposes typed parameters (not opaque kwargs)")
else:
    print(f"FAIL  tool args schema looks wrong: {schema}")
    FAILURES.append("tool args schema")
by_name["get_pod_statuses"].invoke({"namespace": NS})
by_name["get_pod_statuses"].invoke({"namespace": "kube-system"})  # should be caught, not raised
entries = get_audit_log()
if len(entries) == 2 and entries[0].success and not entries[1].success:
    print("OK    audit log correctly records success and failure")
else:
    print(f"FAIL  audit log unexpected state: {audit_log_as_text()}")
    FAILURES.append("audit log")

print("\n" + "=" * 50)
if FAILURES:
    print(f"{len(FAILURES)} CHECK(S) FAILED: {FAILURES}")
    sys.exit(1)
print("All smoke checks passed.")
