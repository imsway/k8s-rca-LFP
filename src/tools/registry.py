"""LangChain @tool wrappers with audit logging, error containment, and transient retry."""
from __future__ import annotations

import functools
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from langchain_core.tools import tool

from src.tools import kubernetes as k8s
from src.tools import loki
from src.tools import prometheus as prom
from src.tools import traces

MAX_RETRIES = 2
RETRY_DELAY_S = 1.0
_TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError)


@dataclass
class AuditEntry:
    tool: str
    args: dict[str, Any]
    success: bool
    duration_ms: float
    summary: str
    retries: int = 0
    timestamp: float = field(default_factory=time.time)


_AUDIT_LOG: list[AuditEntry] = []


def get_audit_log() -> list[AuditEntry]:
    return list(_AUDIT_LOG)


def clear_audit_log() -> None:
    _AUDIT_LOG.clear()


def audit_log_as_text() -> str:
    lines = []
    for e in _AUDIT_LOG:
        status = "OK" if e.success else "ERROR"
        retry_info = f" (retried {e.retries}x)" if e.retries > 0 else ""
        lines.append(f"[{status}] {e.tool}({e.args}) -- {e.duration_ms:.0f}ms{retry_info} -- {e.summary}")
    return "\n".join(lines)


def _record(name: str, args: dict, start: float, result: Any, error: Optional[Exception],
            retries: int = 0) -> None:
    duration_ms = (time.perf_counter() - start) * 1000
    if error is not None:
        _AUDIT_LOG.append(AuditEntry(name, args, False, duration_ms,
                                     f"{type(error).__name__}: {error}", retries))
    else:
        text = json.dumps(result, default=str)
        summary = f"{len(text)} chars returned"
        _AUDIT_LOG.append(AuditEntry(name, args, True, duration_ms, summary, retries))


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    try:
        import requests
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
    except ImportError:
        pass
    return False


def _wrap(fn: Callable[..., dict], name: str) -> Callable[..., str]:
    # functools.wraps is required: without it LangChain's @tool sees only **kwargs and loses the schema

    @functools.wraps(fn)
    def wrapper(**kwargs) -> str:
        start = time.perf_counter()
        last_error: Optional[Exception] = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                result = fn(**kwargs)
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES and _is_transient(e):
                    time.sleep(RETRY_DELAY_S)
                    continue
                _record(name, kwargs, start, None, e, retries=attempt)
                return json.dumps({"error": f"{type(e).__name__}: {e}"})
            _record(name, kwargs, start, result, None, retries=attempt)
            return json.dumps(result, default=str)
        _record(name, kwargs, start, None, last_error, retries=MAX_RETRIES)
        return json.dumps({"error": f"{type(last_error).__name__}: {last_error}"})

    return wrapper


def _make_tool(fn: Callable[..., dict]):
    return tool(_wrap(fn, fn.__name__))


KUBERNETES_TOOLS = [_make_tool(f) for f in (
    k8s.get_pod_statuses, k8s.get_pod_logs, k8s.get_pod_description,
    k8s.get_events, k8s.get_deployments, k8s.get_services_and_endpoints,
    k8s.get_configmap, k8s.get_nodes,
)]

PROMETHEUS_TOOLS = [_make_tool(f) for f in (
    prom.query_metric, prom.query_metric_range, prom.get_firing_alerts, prom.get_scrape_targets,
)]

LOKI_TOOLS = [_make_tool(f) for f in (
    loki.query_logs, loki.get_service_names,
)]

TRACE_TOOLS = [_make_tool(f) for f in (
    traces.get_services, traces.get_operations, traces.search_traces, traces.get_trace_detail,
)]

ALL_TOOLS = KUBERNETES_TOOLS + PROMETHEUS_TOOLS + LOKI_TOOLS + TRACE_TOOLS
