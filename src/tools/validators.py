"""Input validation and output truncation for tool modules."""
import os
import re

MAX_QUERY_LENGTH = 500

LIMIT_COMPACT = 3000
LIMIT_LOGS = 6000
LIMIT_METRICS = 4000
LIMIT_TRACES = 8000


class ToolValidationError(ValueError):
    pass


def _allowed_namespaces() -> set[str]:
    raw = os.environ.get("ALLOWED_NAMESPACES", "otel-demo")
    return {ns.strip() for ns in raw.split(",") if ns.strip()}


def validate_namespace(namespace: str) -> str:
    allowed = _allowed_namespaces()
    if namespace not in allowed:
        raise ToolValidationError(
            f"Namespace '{namespace}' is not in the allowed set {sorted(allowed)}. "
            f"This agent may only investigate the namespace(s) it was scoped to."
        )
    return namespace


def _validate_query_string(query: str, label: str) -> str:
    if not query or not query.strip():
        raise ToolValidationError(f"{label} query must not be empty.")
    if len(query) > MAX_QUERY_LENGTH:
        raise ToolValidationError(
            f"{label} query is {len(query)} chars, exceeding the {MAX_QUERY_LENGTH}-char limit. "
            f"Narrow the query (e.g. add more specific label matchers)."
        )
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", query):
        raise ToolValidationError(f"{label} query contains control characters, which is not allowed.")
    return query


def validate_promql(query: str) -> str:
    return _validate_query_string(query, "PromQL")


def validate_logql(query: str) -> str:
    return _validate_query_string(query, "LogQL")


def truncate(text: str, max_chars: int, *, keep: str = "head") -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    marker = f"\n...[truncated {omitted} chars]...\n"
    budget = max_chars - len(marker)
    if budget <= 0:
        return marker.strip()
    if keep == "tail":
        return marker + text[-budget:]
    return text[:budget] + marker
