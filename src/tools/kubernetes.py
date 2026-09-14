"""Read-only Kubernetes observability tools."""
from __future__ import annotations

import ast
import datetime
from functools import lru_cache
from typing import Any, Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from src.tools.validators import LIMIT_COMPACT, LIMIT_LOGS, truncate, validate_namespace


class ToolError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load_config() -> None:
    config.load_kube_config()


def _core_v1() -> client.CoreV1Api:
    _load_config()
    return client.CoreV1Api()


def _apps_v1() -> client.AppsV1Api:
    _load_config()
    return client.AppsV1Api()


def _handle_api_exception(e: ApiException, context: str) -> None:
    if e.status == 403:
        raise ToolError(f"{context}: forbidden by RBAC (this is the sandbox working as intended).")
    if e.status == 404:
        raise ToolError(f"{context}: not found.")
    if e.status == 400 and "log" in context.lower():
        raise ToolError(
            f"{context}: the container has not started yet (still in PodInitializing or "
            f"waiting state). Try again later, or use get_pod_description to check the "
            f"pod's current state and events for why it hasn't started."
        )
    raise ToolError(f"{context}: API error {e.status} - {e.reason}")


def _unwrap_log_bytes_artifact(raw: str) -> str:
    # kubernetes-client sometimes returns "b'...'" instead of decoded text
    if len(raw) >= 2 and raw[0] == "b" and raw[1] in ("'", '"'):
        try:
            unwrapped = ast.literal_eval(raw)
            if isinstance(unwrapped, bytes):
                return unwrapped.decode("utf-8", errors="replace")
        except (ValueError, SyntaxError):
            pass
    return raw


def _age(timestamp: Optional[datetime.datetime]) -> str:
    if timestamp is None:
        return "unknown"
    delta = datetime.datetime.now(datetime.timezone.utc) - timestamp
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h{minutes % 60}m"
    return f"{hours // 24}d{hours % 24}h"


def get_pod_statuses(namespace: str) -> dict[str, Any]:
    """List all pods with phase, readiness, and restart counts."""
    validate_namespace(namespace)
    try:
        pods = _core_v1().list_namespaced_pod(namespace).items
    except ApiException as e:
        _handle_api_exception(e, f"list pods in {namespace}")

    summaries = []
    for pod in pods:
        statuses = pod.status.container_statuses or []
        ready_count = sum(1 for c in statuses if c.ready)
        restarts = sum(c.restart_count for c in statuses)
        reason = None
        for c in statuses:
            if c.state and c.state.waiting:
                reason = c.state.waiting.reason
            elif c.state and c.state.terminated and c.state.terminated.reason not in ("Completed",):
                reason = c.state.terminated.reason
        summaries.append({
            "name": pod.metadata.name,
            "phase": pod.status.phase,
            "ready": f"{ready_count}/{len(statuses)}",
            "restarts": restarts,
            "reason": reason,
            "node": pod.spec.node_name,
            "age": _age(pod.metadata.creation_timestamp),
        })
    return {"namespace": namespace, "pod_count": len(summaries), "pods": summaries}


def get_pod_logs(
    namespace: str,
    pod_name: str,
    container: Optional[str] = None,
    previous: bool = False,
    tail_lines: int = 200,
) -> dict[str, Any]:
    """Tail logs from a pod/container. `previous=True` reads the preceding container instance's logs."""
    validate_namespace(namespace)
    try:
        raw = _core_v1().read_namespaced_pod_log(
            name=pod_name, namespace=namespace, container=container,
            previous=previous, tail_lines=tail_lines, timestamps=True,
        )
    except ApiException as e:
        _handle_api_exception(e, f"read logs for pod {pod_name}")
    return {
        "pod": pod_name, "container": container, "previous": previous,
        "logs": truncate(_unwrap_log_bytes_artifact(raw), LIMIT_LOGS, keep="tail"),
    }


def get_pod_description(namespace: str, pod_name: str) -> dict[str, Any]:
    """Full detail for one pod: container specs, status, and conditions."""
    validate_namespace(namespace)
    try:
        pod = _core_v1().read_namespaced_pod(pod_name, namespace)
    except ApiException as e:
        _handle_api_exception(e, f"describe pod {pod_name}")

    containers = []
    status_by_name = {c.name: c for c in (pod.status.container_statuses or [])}
    for c in pod.spec.containers:
        cs = status_by_name.get(c.name)
        last_state = None
        if cs and cs.last_state:
            if cs.last_state.terminated:
                t = cs.last_state.terminated
                last_state = {"terminated": {"reason": t.reason, "exit_code": t.exit_code,
                                              "finished_at": str(t.finished_at)}}
            elif cs.last_state.waiting:
                last_state = {"waiting": {"reason": cs.last_state.waiting.reason}}
        containers.append({
            "name": c.name,
            "image": c.image,
            "resources": {
                "requests": (c.resources.requests or {}) if c.resources else {},
                "limits": (c.resources.limits or {}) if c.resources else {},
            },
            "ready": cs.ready if cs else None,
            "restart_count": cs.restart_count if cs else None,
            "last_state": last_state,
        })

    conditions = [
        {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
        for c in (pod.status.conditions or [])
    ]
    return {
        "name": pod.metadata.name,
        "namespace": namespace,
        "node": pod.spec.node_name,
        "phase": pod.status.phase,
        "pod_ip": pod.status.pod_ip,
        "containers": containers,
        "conditions": conditions,
    }


def get_events(namespace: str, involved_object_name: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    """Recent Kubernetes events, sorted newest-first."""
    validate_namespace(namespace)
    field_selector = None
    if involved_object_name:
        field_selector = f"involvedObject.name={involved_object_name}"
    try:
        events = _core_v1().list_namespaced_event(namespace, field_selector=field_selector).items
    except ApiException as e:
        _handle_api_exception(e, f"list events in {namespace}")

    def sort_key(e):
        return e.last_timestamp or e.event_time or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    events = sorted(events, key=sort_key, reverse=True)[:limit]
    summaries = [{
        "type": e.type,
        "reason": e.reason,
        "message": e.message,
        "involved_object": f"{e.involved_object.kind}/{e.involved_object.name}",
        "count": e.count,
        "last_seen": _age(e.last_timestamp or e.event_time),
    } for e in events]
    return {"namespace": namespace, "event_count": len(summaries), "events": summaries}


def get_deployments(namespace: str) -> dict[str, Any]:
    """Deployment rollout status: replica counts and conditions."""
    validate_namespace(namespace)
    try:
        deployments = _apps_v1().list_namespaced_deployment(namespace).items
    except ApiException as e:
        _handle_api_exception(e, f"list deployments in {namespace}")

    summaries = []
    for d in deployments:
        conditions = [{"type": c.type, "status": c.status, "reason": c.reason} for c in (d.status.conditions or [])]
        summaries.append({
            "name": d.metadata.name,
            "desired": d.spec.replicas,
            "ready": d.status.ready_replicas or 0,
            "available": d.status.available_replicas or 0,
            "updated": d.status.updated_replicas or 0,
            "conditions": conditions,
        })
    return {"namespace": namespace, "deployments": summaries}


def get_services_and_endpoints(namespace: str) -> dict[str, Any]:
    """Services cross-referenced with their live Endpoints."""
    validate_namespace(namespace)
    try:
        services = _core_v1().list_namespaced_service(namespace).items
        endpoints = _core_v1().list_namespaced_endpoints(namespace).items
    except ApiException as e:
        _handle_api_exception(e, f"list services/endpoints in {namespace}")

    endpoints_by_name = {e.metadata.name: e for e in endpoints}
    summaries = []
    for svc in services:
        ep = endpoints_by_name.get(svc.metadata.name)
        ready_addrs, not_ready_addrs = 0, 0
        if ep and ep.subsets:
            for subset in ep.subsets:
                ready_addrs += len(subset.addresses or [])
                not_ready_addrs += len(subset.not_ready_addresses or [])
        summaries.append({
            "name": svc.metadata.name,
            "cluster_ip": svc.spec.cluster_ip,
            "ports": [{"port": p.port, "target_port": str(p.target_port)} for p in (svc.spec.ports or [])],
            "ready_endpoints": ready_addrs,
            "not_ready_endpoints": not_ready_addrs,
        })
    return {"namespace": namespace, "services": summaries}


def get_configmap(namespace: str, name: str) -> dict[str, Any]:
    """Read a ConfigMap's data."""
    validate_namespace(namespace)
    try:
        cm = _core_v1().read_namespaced_config_map(name, namespace)
    except ApiException as e:
        _handle_api_exception(e, f"read configmap {name}")
    data = {k: truncate(v, LIMIT_COMPACT) for k, v in (cm.data or {}).items()}
    return {"name": name, "namespace": namespace, "data": data}


def get_nodes() -> dict[str, Any]:
    """Node health: conditions and allocatable capacity."""
    try:
        nodes = _core_v1().list_node().items
    except ApiException as e:
        _handle_api_exception(e, "list nodes")

    summaries = []
    for n in nodes:
        conditions = {c.type: c.status for c in (n.status.conditions or [])}
        summaries.append({
            "name": n.metadata.name,
            "conditions": conditions,
            "allocatable": dict(n.status.allocatable or {}),
        })
    return {"nodes": summaries}
