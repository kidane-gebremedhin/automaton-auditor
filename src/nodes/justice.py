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

# Map verdict to 0–10 score for report display (serializer converts to 1–5)
VERDICT_SCORE_0_10 = {VERDICT_FAIL: 2.0, VERDICT_PARTIAL: 5.0, VERDICT_PASS: 8.0}

SCORE_THRESHOLD_PASS = 7
SCORE_THRESHOLD_PARTIAL = 4
VARIANCE_HIGH_THRESHOLD = 3  # max(opinions) - min(opinions) >= this triggers re-eval
TECHLED_WEIGHT = 1.5
PROSECUTOR_WEIGHT = 1.2
DEFENSE_WEIGHT = 0.9

# Phrases that indicate a confirmed vulnerability (not just the word "security")
SECURITY_VULNERABILITY_PHRASES = (
    "security vulnerability", "security flaw", "security risk", "security violation",
    "os.system", "shell injection", "command injection", "unsanitized input",
    "raw os.system", "no error handling", "drops code into", "security negligence",
)


# -----------------------------------------------------------------------------
# Deterministic rules
# -----------------------------------------------------------------------------


def security_override(criterion_id: str, opinions: list[JudicialOpinion], evidences: dict[str, list[Evidence]]) -> str | None:
    """If any opinion or evidence flags a confirmed security vulnerability, override verdict toward FAIL.
    Applied only for safe_tool_engineering so other criteria are not wrongly failed by tooling evidence."""
    if criterion_id != "safe_tool_engineering":
        return None
    arg_lower: str
    for op in opinions:
        arg_lower = (op.argument or "").lower()
        if any(phrase in arg_lower for phrase in SECURITY_VULNERABILITY_PHRASES):
            return VERDICT_FAIL
    for _source, items in (evidences or {}).items():
        for e in items:
            if e.content:
                c = e.content.lower()
                if any(phrase in c for phrase in SECURITY_VULNERABILITY_PHRASES) and (not e.found or e.confidence < 0.5):
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
        return VERDICT_FAIL, "Rule of Evidence: detectives' evidence does not support criterion; Defense overruled."
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


def dissent_requirement(
    opinions: list[JudicialOpinion],
    synthesis_rules: dict | None = None,
) -> bool:
    """True if there is material dissent (variance above threshold)."""
    if len(opinions) < 2:
        return False
    threshold = (synthesis_rules or {}).get("variance_threshold", VARIANCE_HIGH_THRESHOLD)
    scores = [o.score for o in opinions]
    return max(scores) - min(scores) >= threshold


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


def _build_dissent_summary(opinions: list[JudicialOpinion]) -> str | None:
    """When variance >= 2, return one paragraph summarizing the dialectical conflict (Prosecutor vs Defense vs Tech Lead)."""
    if len(opinions) < 2:
        return None
    scores = [o.score for o in opinions]
    if max(scores) - min(scores) < 2:
        return None
    by_judge: dict[str, list[JudicialOpinion]] = defaultdict(list)
    for op in opinions:
        by_judge[op.judge].append(op)
    parts: list[str] = []
    for judge in ("Prosecutor", "Defense", "TechLead"):
        ops = by_judge.get(judge, [])
        if not ops:
            continue
        op = ops[-1]
        arg = (op.argument or "").strip()
        if len(arg) > 200:
            arg = arg[:197] + "..."
        parts.append(f"The {judge} (score {op.score}) argued: {arg}")
    return " ".join(parts) if parts else None


def _evidence_refs_to_locations(
    evidences: dict[str, list[Evidence]],
    evidence_refs: list[str],
) -> list[str]:
    """Resolve evidence refs (e.g. repo#0) to file/location paths from evidences."""
    locations: list[str] = []
    for ref in evidence_refs or []:
        if "#" not in ref:
            continue
        source, idx_str = ref.split("#", 1)
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        items = (evidences or {}).get(source, [])
        if 0 <= idx < len(items) and items[idx].location:
            loc = items[idx].location.strip()
            if loc and loc not in locations:
                locations.append(loc)
    return locations


def _build_remediation_file_level(
    criterion_id: str,
    verdict: str,
    summary: str,
    evidence_locations: list[str] | None = None,
    dimension_name: str = "",
    dimension_description: str = "",
) -> str:
    """Detailed file- and architecture-level remediation (files to change, architecture updates)."""
    if verdict == VERDICT_PASS:
        return ""
    parts: list[str] = []
    parts.append(f"Address **{dimension_name or criterion_id}**: {summary}")
    if evidence_locations:
        parts.append(f" **Files to update**: {', '.join(evidence_locations)}.")
    if dimension_description:
        arch_hint = dimension_description.strip()[:300]
        if arch_hint:
            parts.append(f" **Architecture / requirements**: {arch_hint}.")
    parts.append(" Provide specific file-level or code-level changes where applicable.")
    return "".join(parts)


def _dimension_name_for(criterion_id: str, rubric_dimensions: list[dict] | None) -> str:
    """Human-readable dimension name from rubric; fallback to criterion_id."""
    for d in (rubric_dimensions or []):
        if d.get("id") == criterion_id:
            return (d.get("name") or criterion_id).strip()
    return criterion_id.replace("_", " ").title()


def _dimension_description_for(criterion_id: str, rubric_dimensions: list[dict] | None) -> str:
    """Description (success/forensic instruction) for this dimension; for remediation architecture hint."""
    for d in (rubric_dimensions or []):
        if d.get("id") == criterion_id:
            return (d.get("description") or "").strip()
    return ""


def _synthesize_criterion(
    criterion_id: str,
    opinions: list[JudicialOpinion],
    evidences: dict[str, list[Evidence]],
    synthesis_rules: dict | None = None,
    rubric_dimensions: list[dict] | None = None,
) -> CriterionResult:
    """Apply all rules in order; output verdict, summary, dissent_summary, remediation. synthesis_rules from rubric when provided."""
    dimension_name = _dimension_name_for(criterion_id, rubric_dimensions)

    # 1) Rule of Security (confirmed vulnerability overrides effort; cap score)
    sec = security_override(criterion_id, opinions, evidences)
    if sec is not None:
        refs_sec = [ref for op in opinions for ref in (op.cited_evidence or [])][:10]
        remediation_sec = _build_remediation_file_level(
            criterion_id, sec, "Rule of Security applied; address security findings.",
            evidence_locations=_evidence_refs_to_locations(evidences, refs_sec),
            dimension_name=dimension_name,
            dimension_description=_dimension_description_for(criterion_id, rubric_dimensions),
        )
        return CriterionResult(
            criterion_id=criterion_id,
            verdict=sec,
            summary="Rule of Security applied: confirmed security concern overrides effort points; score capped.",
            evidence_refs=refs_sec,
            dimension_name=dimension_name,
            final_score=VERDICT_SCORE_0_10.get(sec, 2.0),
            dissent_summary=None,
            remediation=remediation_sec,
        )

    # 2) Fact supremacy
    fact_verdict, fact_summary = fact_supremacy(opinions, evidences)

    # 3) Weighted score (functionality_weight)
    weighted = functionality_weight(opinions)

    # 4) Dissent
    dissent = dissent_requirement(opinions, synthesis_rules)

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
    refs = list(dict.fromkeys(refs))[:10]
    dissent_summary = _build_dissent_summary(opinions) if dissent else None
    remediation = _build_remediation_file_level(
        criterion_id,
        verdict,
        summary or "",
        evidence_locations=_evidence_refs_to_locations(evidences, refs),
        dimension_name=dimension_name,
        dimension_description=_dimension_description_for(criterion_id, rubric_dimensions),
    )

    # Verdict score must reflect the synthesis outcome (conflict resolution), not raw weighted average.
    # So the displayed 1–5 score matches PASS/PARTIAL/FAIL after variance re-evaluation and rules.
    score_0_10 = VERDICT_SCORE_0_10.get(verdict, 2.0)
    return CriterionResult(
        criterion_id=criterion_id,
        verdict=verdict,
        summary=summary or f"Weighted score {weighted:.1f}.",
        evidence_refs=refs,
        dimension_name=dimension_name,
        final_score=score_0_10,
        dissent_summary=dissent_summary,
        remediation=remediation,
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
    """Bullet list of file-level actions for FAIL and PARTIAL (Digital Courtroom spec)."""
    lines: list[str] = []
    for c in criterion_results:
        if c.verdict in (VERDICT_FAIL, VERDICT_PARTIAL):
            name = c.dimension_name or c.criterion_id
            if c.remediation:
                lines.append(f"- **{name}** ({c.verdict}): {c.remediation}")
            else:
                lines.append(f"- **{name}** ({c.verdict}): {c.summary}")
    return "\n".join(lines) if lines else "No remediation required for this audit."


def chief_justice(state: AgentState) -> dict:
    """Run deterministic synthesis using state.synthesis_rules when present; output criterion_results and final_report (AuditReport)."""
    opinions: list[JudicialOpinion] = list(state.get("opinions") or [])
    evidences: dict[str, list[Evidence]] = dict(state.get("evidences") or {})
    # synthesis_rules from rubric (ContextBuilder) can override thresholds; used in _synthesize_criterion via module defaults
    _state_synthesis_rules = state.get("synthesis_rules") or {}

    # Group by criterion_id; keep at most one opinion per judge per criterion (first occurrence)
    by_criterion: dict[str, list[JudicialOpinion]] = defaultdict(list)
    for op in opinions:
        cid = op.criterion_id
        existing_judges = {o.judge for o in by_criterion[cid]}
        if op.judge not in existing_judges:
            by_criterion[cid].append(op)

    # If no opinions, use a single synthetic criterion
    if not by_criterion:
        by_criterion["overall"] = []

    rubric_dimensions = state.get("rubric_dimensions") or []
    criterion_results: list[CriterionResult] = []
    for cid, ops in by_criterion.items():
        criterion_results.append(
            _synthesize_criterion(
                cid, ops, evidences, _state_synthesis_rules, rubric_dimensions
            )
        )

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
