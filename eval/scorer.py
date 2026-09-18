"""Scores an RCAReport against a scenario's ground truth across 5 weighted criteria."""
from __future__ import annotations

from dataclasses import dataclass

from scenarios.base import BaseScenario
from src.models.rca_report import RCAReport


@dataclass
class ScoreBreakdown:
    root_cause_id: float
    evidence_quality: float
    hypothesis_discipline: float
    confidence_calibration: float
    completeness: float

    scenario_name: str = ""
    notes: list[str] | None = None

    @property
    def composite(self) -> float:
        return (
            0.30 * self.root_cause_id
            + 0.20 * self.evidence_quality
            + 0.15 * self.hypothesis_discipline
            + 0.15 * self.confidence_calibration
            + 0.20 * self.completeness
        )


def _service_match(report_service: str, ground_truth_service: str) -> bool:
    a = report_service.lower().strip().replace("-", "").replace("_", "")
    b = ground_truth_service.lower().strip().replace("-", "").replace("_", "")
    return a == b or a in b or b in a


def _type_match(report_type: str, ground_truth_type: str) -> bool:
    a = report_type.lower().strip().replace("-", "_")
    b = ground_truth_type.lower().strip().replace("-", "_")
    if a == b or a in b or b in a:
        return True
    config_aliases = {"configuration", "config", "feature_flag", "configuration_change"}
    app_error_aliases = {"application_error", "app_error", "application"}
    if a in config_aliases and b in app_error_aliases:
        return True
    if a in app_error_aliases and b in config_aliases:
        return True
    return False


def score_report(report: RCAReport, scenario: BaseScenario) -> ScoreBreakdown:
    notes: list[str] = []

    # --- 1. Root cause identification ---
    service_ok = _service_match(report.root_cause_service, scenario.root_cause_service)
    type_ok = _type_match(report.root_cause_type, scenario.root_cause_type)
    rc_text = report.root_cause.lower()
    gt_service = scenario.root_cause_service.lower()
    root_cause_mentioned = gt_service in rc_text or gt_service in report.root_cause_service.lower()

    if service_ok and type_ok:
        root_cause_id = 1.0
    elif service_ok:
        root_cause_id = 0.7
        notes.append(f"Service correct but type mismatch: got '{report.root_cause_type}', "
                     f"expected '{scenario.root_cause_type}'")
    elif root_cause_mentioned:
        root_cause_id = 0.4
        notes.append(f"Root cause text mentions '{scenario.root_cause_service}' but "
                     f"root_cause_service field is '{report.root_cause_service}'")
    else:
        root_cause_id = 0.0
        notes.append(f"Wrong service: got '{report.root_cause_service}', "
                     f"expected '{scenario.root_cause_service}'")

    # --- 2. Evidence quality ---
    evidence_count = len(report.evidence)
    has_specific_evidence = any(
        any(kw in e.lower() for kw in ["log", "trace", "metric", "event", "pod", "span", "flag"])
        for e in report.evidence
    )
    if evidence_count >= 3 and has_specific_evidence:
        evidence_quality = 1.0
    elif evidence_count >= 2:
        evidence_quality = 0.7
    elif evidence_count >= 1:
        evidence_quality = 0.4
    else:
        evidence_quality = 0.0
        notes.append("No evidence cited in report")

    # --- 3. Hypothesis discipline ---
    hyp_count = len(report.hypotheses_considered)
    has_alternatives = len(report.alternative_explanations) > 0
    alternatives_have_reasons = all(
        len(alt.why_not_favored.strip()) > 10
        for alt in report.alternative_explanations
    )

    if hyp_count >= 2 and has_alternatives and alternatives_have_reasons:
        hypothesis_discipline = 1.0
    elif hyp_count >= 2 and has_alternatives:
        hypothesis_discipline = 0.7
    elif hyp_count >= 2:
        hypothesis_discipline = 0.5
        notes.append("Multiple hypotheses but no alternative explanations section")
    else:
        hypothesis_discipline = 0.2
        notes.append(f"Only {hyp_count} hypothesis considered")

    # --- 4. Confidence calibration ---
    if service_ok:
        if report.confidence >= 0.6:
            confidence_calibration = 1.0
        elif report.confidence >= 0.4:
            confidence_calibration = 0.7
            notes.append(f"Correct root cause but low confidence ({report.confidence:.2f})")
        else:
            confidence_calibration = 0.4
            notes.append(f"Correct root cause but very low confidence ({report.confidence:.2f})")
    else:
        if report.confidence <= 0.4:
            confidence_calibration = 0.6
            notes.append("Wrong root cause but appropriately low confidence")
        elif report.confidence <= 0.6:
            confidence_calibration = 0.3
        else:
            confidence_calibration = 0.0
            notes.append(f"Wrong root cause with high confidence ({report.confidence:.2f})")

    # --- 5. Completeness ---
    completeness_checks = [
        len(report.timeline) >= 1,
        len(report.recommended_actions) >= 1,
        len(report.uncertainty.strip()) > 10,
        len(report.affected_services) >= 1,
        len(report.observed_facts) >= 2,
        len(report.investigation_summary.strip()) > 20,
    ]
    completeness = sum(completeness_checks) / len(completeness_checks)
    missing = []
    labels = ["timeline", "recommended_actions", "uncertainty", "affected_services",
              "observed_facts (>=2)", "investigation_summary"]
    for label, ok in zip(labels, completeness_checks):
        if not ok:
            missing.append(label)
    if missing:
        notes.append(f"Missing/thin sections: {', '.join(missing)}")

    return ScoreBreakdown(
        root_cause_id=root_cause_id,
        evidence_quality=evidence_quality,
        hypothesis_discipline=hypothesis_discipline,
        confidence_calibration=confidence_calibration,
        completeness=completeness,
        scenario_name=scenario.name,
        notes=notes,
    )
