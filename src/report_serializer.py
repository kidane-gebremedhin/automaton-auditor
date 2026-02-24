"""Report serializer: convert AuditReport + opinions to full Markdown and save to audit dirs."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from src.state import AuditReport, CriterionResult, JudicialOpinion

# Audit output directories (relative to project root)
REPORT_ON_SELF_DIR = "audit/report_onself_generated"
REPORT_ON_PEER_DIR = "audit/report_onpeer_generated"
DEFAULT_FILENAME = "audit_report.md"


def _compute_final_score(criterion_breakdown: list[CriterionResult]) -> float:
    """Compute final score: PASS=1, PARTIAL=0.5, FAIL=0; return average 0–1."""
    if not criterion_breakdown:
        return 0.0
    total = 0.0
    for c in criterion_breakdown:
        if c.verdict == "PASS":
            total += 1.0
        elif c.verdict == "PARTIAL":
            total += 0.5
        else:
            total += 0.0
    return total / len(criterion_breakdown)


def _dissent_summary(opinions: list[JudicialOpinion]) -> str:
    """Summarize dissent: criteria where judge scores differ by >= 3."""
    by_criterion: dict[str, list[JudicialOpinion]] = defaultdict(list)
    for op in opinions:
        by_criterion[op.criterion_id].append(op)
    lines: list[str] = []
    for cid, ops in by_criterion.items():
        if len(ops) < 2:
            continue
        scores = [o.score for o in ops]
        if max(scores) - min(scores) >= 3:
            lines.append(f"- **{cid}**: scores {scores} (Prosecutor/Defense/TechLead or subset)")
    return "\n".join(lines) if lines else "No material dissent (all criteria had low score variance)."


def serialize_report_to_markdown(
    report: AuditReport,
    opinions: list[JudicialOpinion] | None = None,
) -> str:
    """Convert AuditReport and optional opinions to full Markdown.

    Sections: Executive Summary, Criterion Breakdown (up to 10), Final Score,
    Judge Opinions, Dissent Summary, Remediation, Final Remediation Plan.
    """
    opinions = opinions or []
    parts: list[str] = []

    # Title
    parts.append("# Audit Report\n\n")

    # 1. Executive Summary
    parts.append("## Executive Summary\n\n")
    parts.append(report.executive_summary.strip())
    parts.append("\n\n")

    # 2. Criterion Breakdown (up to 10 sections)
    parts.append("## Criterion Breakdown\n\n")
    for i, c in enumerate(report.criterion_breakdown[:10]):
        parts.append(f"### {i + 1}. {c.criterion_id}\n\n")
        parts.append(f"- **Verdict**: {c.verdict}\n")
        parts.append(f"- **Summary**: {c.summary}\n")
        if c.evidence_refs:
            parts.append(f"- **Evidence refs**: {', '.join(c.evidence_refs[:5])}\n")
        parts.append("\n")
    if len(report.criterion_breakdown) > 10:
        parts.append(f"*... and {len(report.criterion_breakdown) - 10} more criteria.*\n\n")

    # 3. Final Score
    score = _compute_final_score(report.criterion_breakdown)
    pct = round(score * 100, 1)
    parts.append("## Final Score\n\n")
    parts.append(f"{pct}% (score: {score:.2f} / 1.00)\n\n")

    # 4. Judge Opinions
    parts.append("## Judge Opinions\n\n")
    by_criterion: dict[str, list[JudicialOpinion]] = defaultdict(list)
    for op in opinions:
        by_criterion[op.criterion_id].append(op)
    for cid in sorted(by_criterion.keys()):
        parts.append(f"### {cid}\n\n")
        for op in by_criterion[cid]:
            parts.append(f"- **{op.judge}** (score {op.score}): {op.argument}\n")
            if op.cited_evidence:
                parts.append(f"  Cited: {', '.join(op.cited_evidence[:3])}\n")
        parts.append("\n")
    if not opinions:
        parts.append("No judge opinions in state.\n\n")

    # 5. Dissent Summary
    parts.append("## Dissent Summary\n\n")
    parts.append(_dissent_summary(opinions))
    parts.append("\n\n")

    # 6. Remediation (same as criterion breakdown FAIL/PARTIAL items, listed again)
    parts.append("## Remediation\n\n")
    for c in report.criterion_breakdown:
        if c.verdict in ("FAIL", "PARTIAL"):
            parts.append(f"- **{c.criterion_id}** ({c.verdict}): {c.summary}\n")
    if not any(c.verdict in ("FAIL", "PARTIAL") for c in report.criterion_breakdown):
        parts.append("No remediation required.\n")
    parts.append("\n")

    # 7. Final Remediation Plan
    parts.append("## Final Remediation Plan\n\n")
    parts.append(report.remediation_plan.strip())
    parts.append("\n")

    return "".join(parts)


def save_report_markdown(
    markdown: str,
    output_dir: Path | str,
    filename: str = DEFAULT_FILENAME,
) -> Path:
    """Write markdown to output_dir/filename. Creates dirs if needed. Returns path."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def save_report_to_audit_dirs(
    report: AuditReport,
    opinions: list[JudicialOpinion] | None = None,
    project_root: Path | str | None = None,
    self_audit_only: bool = False,
) -> tuple[Path, Path]:
    """Serialize report and save to audit dirs.

    If self_audit_only is True, write only to audit/report_onself_generated.
    Otherwise write to both report_onself_generated and report_onpeer_generated.
    Returns (path_self, path_peer); path_peer is None when self_audit_only.
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
    markdown = serialize_report_to_markdown(report, opinions)
    path_self = save_report_markdown(markdown, root / REPORT_ON_SELF_DIR)
    path_peer = path_self
    if not self_audit_only:
        path_peer = save_report_markdown(markdown, root / REPORT_ON_PEER_DIR)
    return path_self, path_peer
