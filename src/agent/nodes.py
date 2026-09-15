"""Graph node functions: TRIAGE, INVESTIGATE, SYNTHESIZE, and the routing decision."""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.prompts import SYNTHESIS_INSTRUCTIONS, TRIAGE_PREFIX, build_system_prompt
from src.agent.state import InvestigationState
from src.llm.base import get_llm, get_structured_llm
from src.models.evidence import Evidence
from src.models.hypothesis import InvestigationUpdate
from src.models.rca_report import RCAReport
from src.tools import kubernetes as k8s
from src.tools import prometheus as prom
from src.tools.registry import ALL_TOOLS

_NAMESPACE = "otel-demo"  # the one namespace this agent is scoped to; see setup/rbac/

_TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}

_MAX_CONTEXT_MESSAGES = 40


def _max_tool_calls_per_turn() -> int:
    return int(os.environ.get("MAX_TOOL_CALLS_PER_TURN", 5))


def _new_evidence(tool_name: str, tool_args: dict, result: dict) -> Evidence:
    return Evidence(id=str(uuid.uuid4())[:8], tool_name=tool_name, tool_args=tool_args,
                     result=json.dumps(result, default=str))


def _extract_active_flags(flagd_config: dict) -> dict:
    """Return only flags whose defaultVariant != 'off'."""
    try:
        raw_json = flagd_config.get("data", {}).get("demo.flagd.json", "{}")
        raw_json = raw_json.replace("\r\n", "\n").replace("\r", "\n")
        try:
            config = json.loads(raw_json)
        except json.JSONDecodeError:
            import re
            matches = re.findall(
                r'"(\w+)":\s*\{[^}]*"defaultVariant":\s*"([^"]+)"[^}]*"description":\s*"([^"]*)"',
                raw_json,
            )
            active = {}
            for name, variant, desc in matches:
                if variant != "off":
                    active[name] = {"defaultVariant": variant, "description": desc}
            if not active:
                return {"status": "all flags are off (baseline)"}
            return {"active_flags": active, "count": len(active), "note": "parsed via regex (JSON was truncated)"}
        flags = config.get("flags", {})
        active = {}
        for name, flag in flags.items():
            variant = flag.get("defaultVariant", "off")
            if variant != "off":
                active[name] = {"defaultVariant": variant, "description": flag.get("description", "")}
        if not active:
            return {"status": "all flags are off (baseline)"}
        return {"active_flags": active, "count": len(active)}
    except Exception as e:
        return {"error": f"Failed to parse flagd config: {e}"}


def _prune_messages(messages: list) -> list:
    """Collapse old investigation turns into a summary to bound context size."""
    if len(messages) <= _MAX_CONTEXT_MESSAGES:
        return messages

    preserved_head = messages[:2]
    recent = messages[-(_MAX_CONTEXT_MESSAGES - 3):]

    pruned_middle = messages[2:-(_MAX_CONTEXT_MESSAGES - 3)]
    tool_names_seen = []
    for msg in pruned_middle:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_names_seen.append(tc["name"])

    summary = (
        f"[Earlier investigation turns pruned to save context. "
        f"Tools called in pruned turns: {', '.join(tool_names_seen) or 'none'}. "
        f"Their results informed the hypotheses visible in later turns. "
        f"Do NOT repeat these tool calls -- their findings are already reflected "
        f"in your current hypothesis set.]"
    )
    return preserved_head + [HumanMessage(content=summary)] + recent


def triage_node(state: InvestigationState) -> dict:
    try:
        pod_statuses = k8s.get_pod_statuses(_NAMESPACE)
    except Exception as e:
        pod_statuses = {"error": f"Failed to fetch pod statuses: {e}"}
    try:
        events = k8s.get_events(_NAMESPACE, limit=20)
    except Exception as e:
        events = {"error": f"Failed to fetch events: {e}"}
    try:
        alerts = prom.get_firing_alerts()
    except Exception as e:
        alerts = {"error": f"Failed to fetch alerts: {e}"}
    try:
        k8s._load_config()
        cm = k8s._core_v1().read_namespaced_config_map("flagd-config", _NAMESPACE)
        raw_data = {"data": dict(cm.data or {})}
        active_flags = _extract_active_flags(raw_data)
    except Exception as e:
        active_flags = {"error": f"Failed to fetch flagd config: {e}"}

    evidence = [
        _new_evidence("get_pod_statuses", {"namespace": _NAMESPACE}, pod_statuses),
        _new_evidence("get_events", {"namespace": _NAMESPACE, "limit": 20}, events),
        _new_evidence("get_firing_alerts", {}, alerts),
        _new_evidence("get_configmap", {"namespace": _NAMESPACE, "name": "flagd-config"}, active_flags),
    ]

    triage_summary = (
        f"{TRIAGE_PREFIX}\n"
        f"--- pod statuses ---\n{json.dumps(pod_statuses, default=str)}\n\n"
        f"--- recent events ---\n{json.dumps(events, default=str)}\n\n"
        f"--- firing alerts ---\n{json.dumps(alerts, default=str)}\n\n"
        f"--- active feature flags (non-off defaultVariant) ---\n{json.dumps(active_flags, default=str)}"
    )

    system_prompt = build_system_prompt(state["tool_call_budget"], state["max_iterations"])
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Incident report: {state['incident_description']}\n\n{triage_summary}"),
    ]

    return {"messages": messages, "evidence": evidence, "iteration": 1}


def investigate_node(state: InvestigationState) -> dict:
    max_per_turn = _max_tool_calls_per_turn()
    messages = _prune_messages(state["messages"])
    llm = get_llm(tools=ALL_TOOLS + [InvestigationUpdate])
    response: AIMessage = llm.invoke(messages)

    new_evidence: list[Evidence] = []
    new_history: list[str] = []
    tool_messages: list[ToolMessage] = []
    hypotheses_update = None

    pending_calls: list[dict] = []

    for call in (response.tool_calls or []):
        call_id, name, args = call["id"], call["name"], call["args"]

        if name == "InvestigationUpdate":
            try:
                hypotheses_update = InvestigationUpdate(**args)
                tool_messages.append(ToolMessage(content="Hypotheses recorded.", tool_call_id=call_id))
            except Exception as e:
                tool_messages.append(ToolMessage(content=f"Rejected: {e}", tool_call_id=call_id))
            continue

        if name not in _TOOLS_BY_NAME:
            tool_messages.append(ToolMessage(content=f"Error: unknown tool '{name}'.", tool_call_id=call_id))
            continue

        call_key = f"{name}({json.dumps(args, sort_keys=True, default=str)})"
        if call_key in state["tool_call_history"]:
            tool_messages.append(ToolMessage(
                content="Skipped: an identical call was already made earlier in this investigation. "
                        "Check the earlier tool result in this conversation instead of repeating it.",
                tool_call_id=call_id,
            ))
            continue

        if len(pending_calls) >= max_per_turn:
            tool_messages.append(ToolMessage(
                content=f"Skipped: per-turn limit of {max_per_turn} tool calls reached. "
                        f"This can be called on a future turn instead.",
                tool_call_id=call_id,
            ))
            continue

        pending_calls.append({"call_id": call_id, "name": name, "args": args, "call_key": call_key})

    # Execute pending tool calls in parallel
    results_by_call_id: dict[str, str] = {}
    if pending_calls:
        with ThreadPoolExecutor(max_workers=min(len(pending_calls), max_per_turn)) as executor:
            future_to_call = {
                executor.submit(_TOOLS_BY_NAME[pc["name"]].invoke, pc["args"]): pc
                for pc in pending_calls
            }
            for future in as_completed(future_to_call):
                pc = future_to_call[future]
                results_by_call_id[pc["call_id"]] = future.result()

    for pc in pending_calls:
        result_json = results_by_call_id[pc["call_id"]]
        tool_messages.append(ToolMessage(content=result_json, tool_call_id=pc["call_id"]))
        new_evidence.append(_new_evidence(pc["name"], pc["args"], json.loads(result_json)))
        new_history.append(pc["call_key"])

    real_calls_made = len(pending_calls)

    if real_calls_made == 0 and state["tool_calls_used"] < state["tool_call_budget"]:
        remaining_budget = state["tool_call_budget"] - state["tool_calls_used"]
        nudge = HumanMessage(content=(
            f"You made 0 investigation tool calls this turn (only InvestigationUpdate). "
            f"You still have {remaining_budget} tool calls remaining in your budget. "
            f"You MUST call at least 2 investigation tools per turn to make progress. "
            f"Consider: query_logs for service-level errors, search_traces for error traces, "
            f"query_metric for error rates or latency, get_pod_logs for container output, "
            f"or get_configmap for feature-flag state. What specific evidence would confirm "
            f"or refute your top hypothesis?"
        ))
        tool_messages.append(nudge)

    update: dict = {
        "messages": [response, *tool_messages],
        "evidence": new_evidence,
        "tool_call_history": new_history,
        "iteration": state["iteration"] + 1,
        "tool_calls_used": state["tool_calls_used"] + real_calls_made,
    }
    if hypotheses_update is not None:
        update["hypotheses"] = hypotheses_update.hypotheses
        update["overall_confidence"] = hypotheses_update.overall_confidence
        update["ready_to_conclude"] = hypotheses_update.ready_to_conclude
    return update


def route_after_investigate(state: InvestigationState) -> Literal["investigate", "synthesize"]:
    if state["ready_to_conclude"]:
        return "synthesize"
    if state["iteration"] >= state["max_iterations"]:
        return "synthesize"
    if state["tool_calls_used"] >= state["tool_call_budget"]:
        return "synthesize"
    return "investigate"


def synthesize_node(state: InvestigationState) -> dict:
    messages = _prune_messages(state["messages"])
    structured_llm = get_structured_llm(RCAReport)
    messages = [*messages, HumanMessage(content=SYNTHESIS_INSTRUCTIONS)]
    report: RCAReport = structured_llm.invoke(messages)
    return {"rca_report": report, "messages": [HumanMessage(content=SYNTHESIS_INSTRUCTIONS)]}
