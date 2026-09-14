"""Loki log query tools."""
from __future__ import annotations

import os
import time
from typing import Any

import requests

from src.tools.validators import LIMIT_LOGS, ToolValidationError, truncate, validate_logql

_TIMEOUT = 15


class ToolError(RuntimeError):
    pass


def _base_url() -> str:
    url = os.environ.get("LOKI_URL")
    if not url:
        raise ToolValidationError("LOKI_URL is not configured.")
    return url.rstrip("/")


def _get(path: str, params: dict) -> dict:
    try:
        resp = requests.get(f"{_base_url()}{path}", params=params, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ToolError(f"Loki request to {path} failed: {e}")
    if resp.status_code != 200:
        raise ToolError(f"Loki returned HTTP {resp.status_code} for {path}: {resp.text[:300]}")
    body = resp.json()
    if body.get("status") != "success":
        raise ToolError(f"Loki query error: {body.get('error', body)}")
    return body["data"]


def query_logs(logql: str, lookback_minutes: int = 15, limit: int = 100) -> dict[str, Any]:
    """LogQL query over the last `lookback_minutes`."""
    validate_logql(logql)
    if not (1 <= lookback_minutes <= 180):
        raise ToolValidationError("lookback_minutes must be between 1 and 180.")
    if not (1 <= limit <= 1000):
        raise ToolValidationError("limit must be between 1 and 1000.")
    end_ns = int(time.time() * 1e9)
    start_ns = end_ns - lookback_minutes * 60 * int(1e9)
    data = _get("/loki/api/v1/query_range", {
        "query": logql, "start": start_ns, "end": end_ns, "limit": limit, "direction": "backward",
    })
    streams = data.get("result", [])
    entries = []
    for stream in streams:
        service = stream.get("stream", {}).get("service_name", "unknown")
        for ts_ns, line in stream.get("values", []):
            entries.append((int(ts_ns), f"[{service}] {line.strip()}"))
    entries.sort(key=lambda e: e[0])
    text = "\n".join(line for _, line in entries)
    return {
        "query": logql, "lookback_minutes": lookback_minutes,
        "stream_count": len(streams), "line_count": len(entries),
        "logs": truncate(text, LIMIT_LOGS, keep="tail"),
    }


def get_service_names() -> dict[str, Any]:
    """List every `service_name` value Loki has seen."""
    data = _get("/loki/api/v1/label/service_name/values", {})
    return {"service_names": data}
