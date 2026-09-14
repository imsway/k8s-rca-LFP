"""Prometheus metrics tools."""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests

from src.tools.validators import LIMIT_METRICS, ToolValidationError, truncate, validate_promql

_TIMEOUT = 10


class ToolError(RuntimeError):
    pass


def _base_url() -> str:
    url = os.environ.get("PROMETHEUS_URL")
    if not url:
        raise ToolValidationError("PROMETHEUS_URL is not configured.")
    return url.rstrip("/")


def _get(path: str, params: dict) -> dict:
    try:
        resp = requests.get(f"{_base_url()}{path}", params=params, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ToolError(f"Prometheus request to {path} failed: {e}")
    if resp.status_code != 200:
        raise ToolError(f"Prometheus returned HTTP {resp.status_code} for {path}: {resp.text[:300]}")
    body = resp.json()
    if body.get("status") != "success":
        raise ToolError(f"Prometheus query error: {body.get('error', body)}")
    return body["data"]


def query_metric(query: str) -> dict[str, Any]:
    """Instant PromQL query."""
    validate_promql(query)
    data = _get("/api/v1/query", {"query": query})
    result_str = str(data.get("result", []))
    return {"query": query, "result_type": data.get("resultType"),
            "result": truncate(result_str, LIMIT_METRICS)}


def query_metric_range(query: str, lookback_minutes: int = 15, step_seconds: int = 15) -> dict[str, Any]:
    """Range PromQL query over the last `lookback_minutes`."""
    validate_promql(query)
    if not (1 <= lookback_minutes <= 180):
        raise ToolValidationError("lookback_minutes must be between 1 and 180.")
    if not (5 <= step_seconds <= 300):
        raise ToolValidationError("step_seconds must be between 5 and 300.")
    end = time.time()
    start = end - lookback_minutes * 60
    data = _get("/api/v1/query_range", {"query": query, "start": start, "end": end, "step": step_seconds})
    result_str = str(data.get("result", []))
    return {"query": query, "lookback_minutes": lookback_minutes,
            "result_type": data.get("resultType"), "result": truncate(result_str, LIMIT_METRICS)}


def get_firing_alerts() -> dict[str, Any]:
    """All currently-firing Prometheus alerts."""
    data = _get("/api/v1/alerts", {})
    firing = [a for a in data.get("alerts", []) if a.get("state") == "firing"]
    summaries = [{
        "labels": a.get("labels"), "annotations": a.get("annotations"),
        "active_since": a.get("activeAt"),
    } for a in firing]
    return {"firing_count": len(summaries), "alerts": summaries}


def get_scrape_targets() -> dict[str, Any]:
    """Health of every Prometheus scrape target."""
    data = _get("/api/v1/targets", {})
    active = data.get("activeTargets", [])
    summaries = [{
        "job": t.get("labels", {}).get("job"),
        "instance": t.get("labels", {}).get("instance"),
        "health": t.get("health"),
        "last_error": t.get("lastError") or None,
    } for t in active]
    down = [s for s in summaries if s["health"] != "up"]
    return {"target_count": len(summaries), "down_count": len(down), "targets": summaries}
