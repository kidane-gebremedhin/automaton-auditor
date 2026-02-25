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


def _score_1_to_5(score_0_10: float) -> int:
    """Map judge/criterion score from 0–10 scale to strict 1–5 scale (Automation Auditor Rubric)."""
    return max(1, min(5, round((score_0_10 / 10.0) * 5)))


def _one_opinion_per_judge(opinions: list[JudicialOpinion]) -> list[JudicialOpinion]:
    """Keep at most one opinion per judge (first occurrence). Ensures one verdict per judge per criterion."""
    seen: set[str] = set()
    out: list[JudicialOpinion] = []
    for op in opinions:
        if op.judge not in seen:
            seen.add(op.judge)
            out.append(op)
    return out


def serialize_report_to_markdown(
    report: AuditReport,
    opinions: list[JudicialOpinion] | None = None,
) -> str:
    """Convert AuditReport and optional opinions to Markdown.

    Follows Digital Courtroom / challenge key points:
    1. Executive Summary — workflow (Detective → Dialectical Bench → Chief Justice), overall verdict, aggregate score on 1–5 scale
    2. Criterion Breakdown — per rubric dimension: final score (1–5), Dialectical Bench (Prosecutor, Defense, Tech Lead) with cited evidence, dissent where applicable
    3. Remediation Plan — specific, file-level instructions for the developer, grouped by criterion
    """
    opinions = opinions or []
    by_criterion: dict[str, list[JudicialOpinion]] = defaultdict(list)
    for op in opinions:
        by_criterion[op.criterion_id].append(op)

    aggregate_0_1 = _compute_final_score(report.criterion_breakdown)
    aggregate_1_5 = _score_1_to_5(aggregate_0_1 * 10)  # 0–1 → 0–10 → 1–5
    pct = round(aggregate_0_1 * 100, 1)

    parts: list[str] = []

    parts.append("# Audit Report\n\n")

    # 1. Executive Summary — overall verdict and aggregate score (1–5 scale)
    parts.append("## Executive Summary\n\n")
    parts.append(
        "This audit was conducted using the **Digital Courtroom** workflow: "
        "the **Detective Layer** (RepoInvestigator, DocAnalyst, VisionInspector) collected forensic evidence in parallel; "
        "evidence was aggregated (Fan-In); the **Dialectical Bench** (Prosecutor, Defense, Tech Lead) evaluated it concurrently (Fan-Out); "
        "the **Chief Justice** applied deterministic synthesis rules (Rule of Security, Rule of Evidence, functionality weight) to produce the final verdict.\n\n"
    )
    parts.append(report.executive_summary.strip())
    parts.append(f"\n\n**Aggregate score**: {aggregate_1_5}/5 ({pct}% of criteria passed or partial).\n\n")

    # 2. Criterion Breakdown — one section per rubric dimension; numeric score (1–5), one verdict per judge
    parts.append("## Criterion Breakdown\n\n")
    for i, c in enumerate(report.criterion_breakdown[:10]):
        title = c.dimension_name or c.criterion_id.replace("_", " ").title()
        parts.append(f"### {i + 1}. {title}\n\n")

        # Numeric verdict only (score 1–5); no PASS/PARTIAL/FAIL as primary
        if c.final_score is not None:
            score_1_5 = _score_1_to_5(c.final_score)
            parts.append(f"- **Verdict (score)**: {score_1_5}/5\n")
        else:
            parts.append(f"- **Verdict (score)**: —\n")

        if c.dissent_summary:
            parts.append(f"- **Dissent summary**: {c.dissent_summary}\n")

        ops = _one_opinion_per_judge(by_criterion.get(c.criterion_id, []))
        if ops:
            parts.append("\n**Dialectical Bench** (one verdict per judge, with cited evidence)\n\n")
            for op in ops:
                s = _score_1_to_5(float(op.score))
                parts.append(f"- **{op.judge}** (verdict {s}/5): {op.argument}\n")
                if op.cited_evidence:
                    parts.append(f"  Cited: {', '.join(op.cited_evidence[:5])}\n")
            parts.append("\n")

        parts.append("\n")
    if len(report.criterion_breakdown) > 10:
        parts.append(f"*... and {len(report.criterion_breakdown) - 10} more criteria.*\n\n")

    # 3. Remediation Plan — specific, file-level instructions for the developer, grouped by criterion
    parts.append("## Remediation Plan\n\n")
    parts.append("*Specific, file-level remediation for the developer, grouped by criterion.*\n\n")
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
