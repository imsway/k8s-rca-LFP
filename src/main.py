"""CLI entry point for the RCA agent."""
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

import logging
import warnings
warnings.filterwarnings("ignore", message=".*automatic function calling.*AFC.*")
warnings.filterwarnings("ignore", message=".*Direct use of automatic function calling.*")
logging.getLogger("google.genai.models").setLevel(logging.ERROR)

from src.agent.graph import build_graph
from src.agent.state import initial_state
from src.tools.registry import audit_log_as_text, clear_audit_log


def _report_to_markdown(report, incident: str, tool_calls_used: int, budget: int, iterations: int) -> str:
    lines = [
        "# Root Cause Analysis Report\n",
        f"**Incident**: {incident}\n",
        f"**Root cause**: {report.root_cause}\n",
        f"| Field | Value |",
        "| --- | --- |",
        f"| Service | {report.root_cause_service} |",
        f"| Type | {report.root_cause_type} |",
        f"| Confidence | {report.confidence:.2f} |",
        f"| Affected services | {', '.join(report.affected_services)} |",
        f"| Tool calls used | {tool_calls_used}/{budget} across {iterations} turn(s) |",
        "",
        f"**Confidence justification**: {report.confidence_justification}\n",
        "## Observed Facts\n",
    ]
    for f in report.observed_facts:
        lines.append(f"- {f}")
    lines += ["", "## Hypotheses Considered\n"]
    for h in report.hypotheses_considered:
        lines.append(f"- {h}")
    lines += ["", "## Evidence\n"]
    for e in report.evidence:
        lines.append(f"- {e}")
    lines += ["", "## Timeline\n"]
    lines.append("| Time | Source | Event |")
    lines.append("| --- | --- | --- |")
    for t in report.timeline:
        lines.append(f"| {t.timestamp} | {t.source} | {t.event} |")
    if report.alternative_explanations:
        lines += ["", "## Alternative Explanations\n"]
        for alt in report.alternative_explanations:
            lines.append(f"- **{alt.description}** — not favored: {alt.why_not_favored}")
    lines += ["", "## Uncertainty\n", report.uncertainty]
    lines += ["", "## Recommended Actions\n"]
    for a in report.recommended_actions:
        lines.append(f"- {a}")
    lines += ["", "## Investigation Summary\n", report.investigation_summary, ""]
    return "\n".join(lines)


def _print_report(report) -> None:
    print("\n" + "=" * 70)
    print("ROOT CAUSE ANALYSIS")
    print("=" * 70)
    print(f"\nRoot cause: {report.root_cause}")
    print(f"Service: {report.root_cause_service}  |  Type: {report.root_cause_type}")
    print(f"Affected services: {', '.join(report.affected_services)}")
    print(f"\nConfidence: {report.confidence:.2f} -- {report.confidence_justification}")

    print("\n--- Observed facts ---")
    for f in report.observed_facts:
        print(f"  - {f}")

    print("\n--- Hypotheses considered ---")
    for h in report.hypotheses_considered:
        print(f"  - {h}")

    print("\n--- Evidence ---")
    for e in report.evidence:
        print(f"  - {e}")

    print("\n--- Timeline ---")
    for t in report.timeline:
        print(f"  [{t.timestamp}] ({t.source}) {t.event}")

    if report.alternative_explanations:
        print("\n--- Alternative explanations ---")
        for alt in report.alternative_explanations:
            print(f"  - {alt.description}\n    (not favored: {alt.why_not_favored})")

    print(f"\n--- Uncertainty ---\n  {report.uncertainty}")

    print("\n--- Recommended actions ---")
    for a in report.recommended_actions:
        print(f"  - {a}")

    print(f"\n--- Investigation summary ---\n{report.investigation_summary}")
    print("=" * 70 + "\n")


@click.command()
@click.option("--incident", required=True, help="Incident description, e.g. a symptom report.")
@click.option("--max-iterations", default=None, type=int, help="Override MAX_ITERATIONS from .env.")
@click.option("--tool-call-budget", default=None, type=int, help="Override TOOL_CALL_BUDGET from .env.")
@click.option("--show-audit-log", is_flag=True, help="Print the full tool-call audit trail after the report.")
@click.option("--output-dir", default=None, type=click.Path(), help="Directory to save the report (default: responses/).")
@click.option("--format", "output_format", default="md", type=click.Choice(["md", "json", "txt", "all"]),
              help="Output file format: md, json, txt, or all (default: md).")
def main(incident: str, max_iterations: int, tool_call_budget: int,
         show_audit_log: bool, output_dir: str | None, output_format: str) -> None:
    import json
    import os
    from datetime import datetime

    max_iter = max_iterations or int(os.environ.get("MAX_ITERATIONS", 8))
    budget = tool_call_budget or int(os.environ.get("TOOL_CALL_BUDGET", 30))

    clear_audit_log()
    graph = build_graph()
    state = initial_state(incident, max_iterations=max_iter, tool_call_budget=budget)

    print(f"Investigating: {incident}")
    print(f"(budget: {budget} tool calls, {max_iter} max turns)\n")

    final_state = graph.invoke(state, config={"recursion_limit": 100})

    report = final_state["rca_report"]
    if report is None:
        print("No report was produced.")
        sys.exit(1)

    _print_report(report)
    tool_calls_used = final_state['tool_calls_used']
    iterations = final_state['iteration']
    print(f"Investigation used {tool_calls_used}/{budget} tool calls "
          f"across {iterations} turn(s).")

    if show_audit_log:
        print("\n--- Full audit log ---")
        print(audit_log_as_text())

    save_dir = Path(output_dir) if output_dir else Path(__file__).resolve().parent.parent / "responses"
    save_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = report.root_cause_service or "unknown"
    base_name = f"rca_{slug}_{timestamp}"
    formats = ["md", "json", "txt"] if output_format == "all" else [output_format]
    saved_files = []

    for fmt in formats:
        filepath = save_dir / f"{base_name}.{fmt}"
        if fmt == "md":
            content = _report_to_markdown(report, incident, tool_calls_used, budget, iterations)
            if show_audit_log:
                content += "\n## Audit Log\n\n```\n" + audit_log_as_text() + "\n```\n"
        elif fmt == "json":
            data = report.model_dump()
            data["_meta"] = {
                "incident": incident,
                "tool_calls_used": tool_calls_used,
                "tool_call_budget": budget,
                "iterations": iterations,
                "timestamp": timestamp,
            }
            content = json.dumps(data, indent=2, default=str)
        else:  # txt
            import io
            buf = io.StringIO()
            _print_report_to(report, buf)
            content = buf.getvalue()
            content += f"\nInvestigation used {tool_calls_used}/{budget} tool calls across {iterations} turn(s).\n"
            if show_audit_log:
                content += "\n--- Full audit log ---\n" + audit_log_as_text() + "\n"
        filepath.write_text(content, encoding="utf-8")
        saved_files.append(filepath)

    for f in saved_files:
        print(f"Report saved: {f}")


def _print_report_to(report, out) -> None:
    p = lambda *a, **kw: print(*a, **kw, file=out)
    p("\n" + "=" * 70)
    p("ROOT CAUSE ANALYSIS")
    p("=" * 70)
    p(f"\nRoot cause: {report.root_cause}")
    p(f"Service: {report.root_cause_service}  |  Type: {report.root_cause_type}")
    p(f"Affected services: {', '.join(report.affected_services)}")
    p(f"\nConfidence: {report.confidence:.2f} -- {report.confidence_justification}")
    p("\n--- Observed facts ---")
    for fact in report.observed_facts:
        p(f"  - {fact}")
    p("\n--- Hypotheses considered ---")
    for h in report.hypotheses_considered:
        p(f"  - {h}")
    p("\n--- Evidence ---")
    for e in report.evidence:
        p(f"  - {e}")
    p("\n--- Timeline ---")
    for t in report.timeline:
        p(f"  [{t.timestamp}] ({t.source}) {t.event}")
    if report.alternative_explanations:
        p("\n--- Alternative explanations ---")
        for alt in report.alternative_explanations:
            p(f"  - {alt.description}\n    (not favored: {alt.why_not_favored})")
    p(f"\n--- Uncertainty ---\n  {report.uncertainty}")
    p("\n--- Recommended actions ---")
    for a in report.recommended_actions:
        p(f"  - {a}")
    p(f"\n--- Investigation summary ---\n{report.investigation_summary}")
    p("=" * 70 + "\n")


if __name__ == "__main__":
    main()
