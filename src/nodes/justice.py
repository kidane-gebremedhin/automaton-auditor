"""Chief Justice: deterministic synthesis of judge opinions.

Hardcoded Python logic only. No LLM. Applies security_override, fact_supremacy,
functionality_weight, dissent_requirement, variance_re_evaluation. Outputs
AuditReport (Executive Summary, Criterion Breakdown, Remediation Plan) and Markdown.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from src.state import (
    AgentState,
    AuditReport,
    CriterionResult,
    Evidence,
    JudicialOpinion,
)

# -----------------------------------------------------------------------------
# Rule constants
# -----------------------------------------------------------------------------

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_PARTIAL = "PARTIAL"

SCORE_THRESHOLD_PASS = 7
SCORE_THRESHOLD_PARTIAL = 4
VARIANCE_HIGH_THRESHOLD = 3  # max(opinions) - min(opinions) >= this triggers re-eval
TECHLED_WEIGHT = 1.5
PROSECUTOR_WEIGHT = 1.2
DEFENSE_WEIGHT = 0.9

SECURITY_KEYWORDS = ("security", "injection", "secret", "credential", "sanitiz", "xss", "csrf")


# -----------------------------------------------------------------------------
# Deterministic rules
# -----------------------------------------------------------------------------


def security_override(criterion_id: str, opinions: list[JudicialOpinion], evidences: dict[str, list[Evidence]]) -> str | None:
    """If any opinion or evidence flags security, override verdict toward FAIL."""
    for op in opinions:
        if any(kw in op.argument.lower() for kw in SECURITY_KEYWORDS):
            return VERDICT_FAIL
    for _source, items in (evidences or {}).items():
        for e in items:
            if e.content and any(kw in e.content.lower() for kw in SECURITY_KEYWORDS):
                if not e.found or e.confidence < 0.5:
                    return VERDICT_FAIL
    return None


def fact_supremacy(
    opinions: list[JudicialOpinion],
    evidences: dict[str, list[Evidence]],
) -> tuple[str, str]:
    """Evidence overrides conflicting opinions. If evidence is clear (high confidence, found), use it."""
    found_any = False
    all_fail_evidence = True
    for _source, items in (evidences or {}).items():
        for e in items:
            if e.goal and e.found and e.confidence >= 0.6:
                found_any = True
                all_fail_evidence = False
    if not found_any and opinions:
        # No strong evidence; defer to weighted scores
        return "", ""
    if all_fail_evidence and opinions:
        return VERDICT_FAIL, "Evidence does not support criterion; fact supremacy yields FAIL."
    return "", ""


def functionality_weight(opinions: list[JudicialOpinion]) -> float:
    """Weighted average: TechLead 1.5, Prosecutor 1.2, Defense 0.9. No LLM."""
    if not opinions:
        return 0.0
    total = 0.0
    wsum = 0.0
    for op in opinions:
        w = TECHLED_WEIGHT if op.judge == "TechLead" else (PROSECUTOR_WEIGHT if op.judge == "Prosecutor" else DEFENSE_WEIGHT)
        total += op.score * w
        wsum += w
    return total / wsum if wsum else 0.0


def dissent_requirement(opinions: list[JudicialOpinion]) -> bool:
    """True if there is material dissent (variance above threshold)."""
    if len(opinions) < 2:
        return False
    scores = [o.score for o in opinions]
    return max(scores) - min(scores) >= VARIANCE_HIGH_THRESHOLD


def variance_re_evaluation(
    weighted_score: float,
    dissent: bool,
    fact_verdict: str,
    fact_summary: str,
    synthesis_rules: dict | None = None,
) -> tuple[str, str]:
    """When variance is high (dissent), re-evaluate. Uses synthesis_rules thresholds when provided."""
    sr = synthesis_rules or {}
    pass_thresh = sr.get("score_threshold_pass", SCORE_THRESHOLD_PASS)
    partial_thresh = sr.get("score_threshold_partial", SCORE_THRESHOLD_PARTIAL)
    if fact_verdict:
        return fact_verdict, fact_summary
    if dissent:
        if weighted_score >= pass_thresh:
            return VERDICT_PARTIAL, "Dissent among judges; downgraded to PARTIAL despite weighted pass."
        if weighted_score >= partial_thresh:
            return VERDICT_PARTIAL, "Dissent among judges; PARTIAL."
        return VERDICT_FAIL, "Dissent among judges; weighted score below threshold."
    if weighted_score >= pass_thresh:
        return VERDICT_PASS, "Weighted score meets pass threshold."
    if weighted_score >= partial_thresh:
        return VERDICT_PARTIAL, "Weighted score in partial range."
    return VERDICT_FAIL, "Weighted score below partial threshold."


# -----------------------------------------------------------------------------
# Synthesize one criterion
# -----------------------------------------------------------------------------


def _synthesize_criterion(
    criterion_id: str,
    opinions: list[JudicialOpinion],
    evidences: dict[str, list[Evidence]],
    synthesis_rules: dict | None = None,
) -> CriterionResult:
    """Apply all rules in order; output verdict and summary. synthesis_rules from rubric when provided."""
    # 1) Security override
    sec = security_override(criterion_id, opinions, evidences)
    if sec is not None:
        return CriterionResult(
            criterion_id=criterion_id,
            verdict=sec,
            summary="Security override applied.",
            evidence_refs=[ref for op in opinions for ref in (op.cited_evidence or [])][:10],
        )

    # 2) Fact supremacy
    fact_verdict, fact_summary = fact_supremacy(opinions, evidences)

    # 3) Weighted score (functionality_weight)
    weighted = functionality_weight(opinions)

    # 4) Dissent
    dissent = dissent_requirement(opinions)

    # 5) Variance re-evaluation (when no opinions, use fact verdict or FAIL)
    if not opinions:
        verdict = fact_verdict or VERDICT_FAIL
        summary = fact_summary or "No judge opinions for this criterion."
    else:
        verdict, summary = variance_re_evaluation(
            weighted, dissent, fact_verdict, fact_summary, synthesis_rules
        )

    refs: list[str] = []
    for op in opinions:
        refs.extend(op.cited_evidence or [])
    return CriterionResult(
        criterion_id=criterion_id,
        verdict=verdict,
        summary=summary or f"Weighted score {weighted:.1f}.",
        evidence_refs=list(dict.fromkeys(refs))[:10],
    )


# -----------------------------------------------------------------------------
# Build AuditReport and Markdown
# -----------------------------------------------------------------------------


def _build_executive_summary(criterion_results: list[CriterionResult]) -> str:
    """One paragraph from criterion outcomes."""
    passed = sum(1 for c in criterion_results if c.verdict == VERDICT_PASS)
    partial = sum(1 for c in criterion_results if c.verdict == VERDICT_PARTIAL)
    failed = sum(1 for c in criterion_results if c.verdict == VERDICT_FAIL)
    total = len(criterion_results)
    return (
        f"This audit evaluated {total} criterion/criteria: {passed} pass, {partial} partial, {failed} fail. "
        "See Criterion Breakdown for details. Remediation Plan lists recommended actions."
    )


def _build_remediation_plan(criterion_results: list[CriterionResult]) -> str:
    """Bullet list of actions for FAIL and PARTIAL."""
    lines: list[str] = []
    for c in criterion_results:
        if c.verdict in (VERDICT_FAIL, VERDICT_PARTIAL):
            lines.append(f"- **{c.criterion_id}** ({c.verdict}): {c.summary}")
    return "\n".join(lines) if lines else "No remediation required for this audit."


def chief_justice(state: AgentState) -> dict:
    """Run deterministic synthesis using state.synthesis_rules when present; output criterion_results and final_report (AuditReport)."""
    opinions: list[JudicialOpinion] = list(state.get("opinions") or [])
    evidences: dict[str, list[Evidence]] = dict(state.get("evidences") or {})
    # synthesis_rules from rubric (ContextBuilder) can override thresholds; used in _synthesize_criterion via module defaults
    _state_synthesis_rules = state.get("synthesis_rules") or {}

    # Group by criterion_id
    by_criterion: dict[str, list[JudicialOpinion]] = defaultdict(list)
    for op in opinions:
        by_criterion[op.criterion_id].append(op)

    # If no opinions, use a single synthetic criterion
    if not by_criterion:
        by_criterion["overall"] = []

    criterion_results: list[CriterionResult] = []
    for cid, ops in by_criterion.items():
        criterion_results.append(_synthesize_criterion(cid, ops, evidences, _state_synthesis_rules))

    executive_summary = _build_executive_summary(criterion_results)
    remediation_plan = _build_remediation_plan(criterion_results)

    report = AuditReport(
        executive_summary=executive_summary,
        criterion_breakdown=criterion_results,
        remediation_plan=remediation_plan,
    )

    return {
        "criterion_results": criterion_results,
        "final_report": report,
    }


def audit_report_to_markdown(report: AuditReport) -> str:
    """Render AuditReport to Markdown (legacy short form). Prefer report_serializer.serialize_report_to_markdown."""
    from src.report_serializer import serialize_report_to_markdown
    return serialize_report_to_markdown(report, opinions=None)


def report_writer(state: AgentState) -> dict:
    """Produce full Markdown report and save to audit/report_onself_generated and audit/report_onpeer_generated."""
    from src.report_serializer import save_report_to_audit_dirs

    report = state.get("final_report")
    if report is None:
        report = AuditReport(
            executive_summary="No opinions or evidence to synthesize.",
            criterion_breakdown=[],
            remediation_plan="N/A",
        )
    opinions = list(state.get("opinions") or [])
    self_audit_only = bool(state.get("self_audit"))
    save_report_to_audit_dirs(report, opinions, self_audit_only=self_audit_only)
    return {"final_report": report}
