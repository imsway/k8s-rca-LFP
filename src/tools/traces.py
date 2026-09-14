"""Jaeger distributed-trace tools."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

import requests

from src.tools.validators import LIMIT_TRACES, ToolValidationError, truncate

_TIMEOUT = 15
_API_PREFIX = "/jaeger/ui/api"


class ToolError(RuntimeError):
    pass


def _base_url() -> str:
    url = os.environ.get("JAEGER_URL")
    if not url:
        raise ToolValidationError("JAEGER_URL is not configured.")
    return url.rstrip("/")


def _get(path: str, params: dict) -> Any:
    try:
        resp = requests.get(f"{_base_url()}{_API_PREFIX}{path}", params=params, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ToolError(f"Jaeger request to {path} failed: {e}")
    if resp.status_code != 200:
        raise ToolError(f"Jaeger returned HTTP {resp.status_code} for {path}: {resp.text[:300]}")
    body = resp.json()
    if body.get("errors"):
        raise ToolError(f"Jaeger query error: {body['errors']}")
    return body["data"]


def get_services() -> dict[str, Any]:
    """List every service Jaeger has traces for."""
    data = _get("/services", {})
    return {"services": data}


def get_operations(service: str) -> dict[str, Any]:
    """List operation names (span names) for a service."""
    data = _get(f"/services/{service}/operations", {})
    return {"service": service, "operations": data}


def search_traces(
    service: str,
    operation: Optional[str] = None,
    error_only: bool = False,
    min_duration_ms: Optional[int] = None,
    lookback_minutes: int = 15,
    limit: int = 20,
) -> dict[str, Any]:
    """Search for trace summaries. `error_only=True` filters to traces with error spans."""
    if not (1 <= lookback_minutes <= 180):
        raise ToolValidationError("lookback_minutes must be between 1 and 180.")
    if not (1 <= limit <= 100):
        raise ToolValidationError("limit must be between 1 and 100.")
    end_us = int(time.time() * 1_000_000)
    start_us = end_us - lookback_minutes * 60 * 1_000_000
    params: dict[str, Any] = {"service": service, "start": start_us, "end": end_us, "limit": limit}
    if operation:
        params["operation"] = operation
    if min_duration_ms is not None:
        params["minDuration"] = f"{min_duration_ms}ms"
    if error_only:
        params["tags"] = json.dumps({"error": "true"})

    data = _get("/traces", params)
    summaries = []
    for trace in data:
        spans = trace.get("spans", [])
        processes = trace.get("processes", {})
        durations = [s.get("duration", 0) for s in spans]

        error_spans = []
        for s in spans:
            tags = {t.get("key"): t.get("value") for t in s.get("tags", [])}
            if str(tags.get("error", "")).lower() == "true":
                error_spans.append({
                    "service": processes.get(s.get("processID"), {}).get("serviceName", "unknown"),
                    "operation": s.get("operationName"),
                    "description": tags.get("otel.status_description"),
                })

        root = min(spans, key=lambda s: s.get("startTime", 0)) if spans else None
        summaries.append({
            "trace_id": trace.get("traceID"),
            "root_operation": root.get("operationName") if root else None,
            "span_count": len(spans),
            "max_span_duration_us": max(durations) if durations else None,
            "has_error": bool(error_spans),
            "error_spans": error_spans,
        })
    return {"service": service, "trace_count": len(summaries), "traces": summaries}


def get_trace_detail(trace_id: str) -> dict[str, Any]:
    """Full span tree for one trace."""
    data = _get(f"/traces/{trace_id}", {})
    if not data:
        raise ToolError(f"Trace {trace_id} not found.")
    trace = data[0]
    processes = trace.get("processes", {})

    spans = []
    for s in trace.get("spans", []):
        service = processes.get(s.get("processID"), {}).get("serviceName", "unknown")
        tags = {t["key"]: t.get("value") for t in s.get("tags", []) if t["key"] in (
            "error", "http.status_code", "http.response.status_code", "rpc.grpc.status_code",
            "feature_flag.key", "feature_flag.result.value", "otel.status_code", "otel.status_description",
        )}
        parent_span_id = next(
            (r["spanID"] for r in s.get("references", []) if r.get("refType") == "CHILD_OF"), None
        )
        spans.append({
            "span_id": s.get("spanID"),
            "parent_span_id": parent_span_id,
            "service": service,
            "operation": s.get("operationName"),
            "duration_us": s.get("duration"),
            "tags": tags,
        })
    spans.sort(key=lambda s: s.get("duration_us") or 0, reverse=True)
    text = json.dumps({"trace_id": trace_id, "span_count": len(spans), "spans": spans}, default=str)
    return {"trace_id": trace_id, "span_count": len(spans),
            "detail": truncate(text, LIMIT_TRACES)}
