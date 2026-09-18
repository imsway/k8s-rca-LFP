"""Evaluation runner: inject scenario, run agent, score report, teardown."""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
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

from eval.scorer import ScoreBreakdown, score_report
from scenarios.registry import CORE_SCENARIOS, SCENARIOS_BY_NAME
from src.agent.graph import build_graph
from src.agent.state import initial_state
from src.tools.registry import audit_log_as_text, clear_audit_log


def _run_agent(incident: str, max_iterations: int, tool_call_budget: int) -> dict:
    clear_audit_log()
    graph = build_graph()
    state = initial_state(incident, max_iterations=max_iterations, tool_call_budget=tool_call_budget)
    return graph.invoke(state, config={"recursion_limit": 100})


def _print_table(scores: list[ScoreBreakdown]) -> None:
    try:
        from tabulate import tabulate
    except ImportError:
        print("\nInstall tabulate for a formatted table: pip install tabulate")
        for s in scores:
            print(f"  {s.scenario_name}: {s.composite:.2f}")
        return

    headers = ["Scenario", "Root Cause", "Evidence", "Hypotheses", "Calibration",
               "Completeness", "COMPOSITE"]
    rows = []
    for s in scores:
        rows.append([
            s.scenario_name,
            f"{s.root_cause_id:.2f}",
            f"{s.evidence_quality:.2f}",
            f"{s.hypothesis_discipline:.2f}",
            f"{s.confidence_calibration:.2f}",
            f"{s.completeness:.2f}",
            f"{s.composite:.2f}",
        ])

    print("\n" + tabulate(rows, headers=headers, tablefmt="grid"))

    composites = [s.composite for s in scores]
    print(f"\nMean composite: {sum(composites) / len(composites):.2f}")
    print(f"Min: {min(composites):.2f}  Max: {max(composites):.2f}")


@click.command()
@click.option("--scenario", default=None, help="Run a single scenario by name (default: all 5).")
@click.option("--max-iterations", default=None, type=int, help="Override MAX_ITERATIONS.")
@click.option("--tool-call-budget", default=None, type=int, help="Override TOOL_CALL_BUDGET.")
@click.option("--dry-run", is_flag=True, help="Skip inject/teardown (assume scenario already active).")
@click.option("--settle-time", default=30, type=int, help="Seconds to wait after injection for effects to appear.")
@click.option("--output-dir", default=None, help="Directory to write JSON result files.")
def main(scenario: str | None, max_iterations: int | None, tool_call_budget: int | None,
         dry_run: bool, settle_time: int, output_dir: str | None) -> None:
    max_iter = max_iterations or int(os.environ.get("MAX_ITERATIONS", 8))
    budget = tool_call_budget or int(os.environ.get("TOOL_CALL_BUDGET", 30))

    if scenario:
        if scenario not in SCENARIOS_BY_NAME:
            print(f"Unknown scenario '{scenario}'. Available: {list(SCENARIOS_BY_NAME.keys())}")
            sys.exit(1)
        scenarios = [SCENARIOS_BY_NAME[scenario]]
    else:
        scenarios = CORE_SCENARIOS

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    scores: list[ScoreBreakdown] = []

    for sc in scenarios:
        print(f"\n{'=' * 60}")
        print(f"SCENARIO: {sc.name}")
        print(f"{'=' * 60}")

        if not dry_run:
            print(f"Injecting {sc.name}...")
            try:
                sc.inject()
            except Exception as e:
                print(f"  INJECT FAILED: {e}")
                print("  Skipping this scenario.")
                continue
            print(f"  Waiting {settle_time}s for effects to propagate...")
            time.sleep(settle_time)

        incident = sc.get_incident_description()
        print(f"Incident: {incident}")
        print(f"Running agent (budget: {budget} calls, {max_iter} turns)...")

        try:
            final_state = _run_agent(incident, max_iter, budget)
        except Exception as e:
            print(f"  AGENT FAILED: {e}")
            if not dry_run:
                print(f"  Tearing down {sc.name}...")
                sc.teardown()
            continue

        report = final_state["rca_report"]
        if report is None:
            print("  No report produced (agent bug).")
            if not dry_run:
                sc.teardown()
            continue

        print(f"  Agent found: service='{report.root_cause_service}', "
              f"type='{report.root_cause_type}', confidence={report.confidence:.2f}")
        print(f"  Tool calls: {final_state['tool_calls_used']}/{budget} "
              f"across {final_state['iteration']} turns")

        breakdown = score_report(report, sc)
        scores.append(breakdown)

        print(f"  COMPOSITE SCORE: {breakdown.composite:.2f}")
        if breakdown.notes:
            for note in breakdown.notes:
                print(f"    - {note}")

        if output_dir:
            result = {
                "scenario": sc.name,
                "ground_truth": {
                    "service": sc.root_cause_service,
                    "type": sc.root_cause_type,
                    "summary": sc.ground_truth_summary,
                },
                "agent_report": {
                    "root_cause": report.root_cause,
                    "root_cause_service": report.root_cause_service,
                    "root_cause_type": report.root_cause_type,
                    "confidence": report.confidence,
                    "confidence_justification": report.confidence_justification,
                    "affected_services": report.affected_services,
                    "observed_facts": report.observed_facts,
                    "hypotheses_considered": report.hypotheses_considered,
                    "evidence": report.evidence,
                    "uncertainty": report.uncertainty,
                    "recommended_actions": report.recommended_actions,
                    "investigation_summary": report.investigation_summary,
                },
                "score": asdict(breakdown),
                "composite": breakdown.composite,
                "tool_calls_used": final_state["tool_calls_used"],
                "iterations": final_state["iteration"],
                "audit_log": audit_log_as_text(),
            }
            out_path = Path(output_dir) / f"{sc.name}.json"
            out_path.write_text(json.dumps(result, indent=2, default=str))
            print(f"  Result written to {out_path}")

        if not dry_run:
            print(f"  Tearing down {sc.name}...")
            try:
                sc.teardown()
            except Exception as e:
                print(f"  TEARDOWN WARNING: {e}")
            print(f"  Waiting {settle_time}s for cluster to settle...")
            time.sleep(settle_time)

    if scores:
        _print_table(scores)
    else:
        print("\nNo scenarios completed successfully.")
        sys.exit(1)


if __name__ == "__main__":
    main()
