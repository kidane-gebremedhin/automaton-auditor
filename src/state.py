"""Agent state and message types for Automaton Auditor.

State Management Rigor: TypedDict + Annotated reducers ensure parallel nodes
can merge their outputs without overwriting each other. Each reducer defines
how to combine the existing state value with an incoming update.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, Optional

from pydantic import BaseModel
from typing_extensions import TypedDict


# -----------------------------------------------------------------------------
# Evidence & judicial models
# -----------------------------------------------------------------------------


class Evidence(BaseModel):
    """Single piece of evidence collected by a detective (repo, docs, vision)."""

    goal: str
    found: bool
    content: Optional[str] = None
    location: str
    rationale: str
    confidence: float


class JudicialOpinion(BaseModel):
    """Opinion from one judge (Prosecutor, Defense, TechLead) on a criterion."""

    judge: Literal["Prosecutor", "Defense", "TechLead"]
    criterion_id: str
    score: int
    argument: str
    cited_evidence: list[str]


class CriterionResult(BaseModel):
    """Synthesized result for one rubric criterion after chief justice."""

    criterion_id: str
    verdict: str  # e.g. PASS, FAIL, PARTIAL
    summary: str
    evidence_refs: list[str] = []


class AuditReport(BaseModel):
    """Final audit report: executive summary, criteria, remediation."""

    executive_summary: str
    criterion_breakdown: list[CriterionResult]
    remediation_plan: str


# -----------------------------------------------------------------------------
# Reducers
# -----------------------------------------------------------------------------


def _last_wins(a: object, b: object) -> object:
    """Reducer: keep the second value if not None (so fan-in multiple writes don't error)."""
    return b if b is not None else a


# -----------------------------------------------------------------------------
# Agent state
# -----------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """State passed through the graph. Reducers prevent parallel overwrites.

    evidences: operator.ior merges update dict into existing. Each key (e.g.
        "repo", "docs") is a source; parallel detectives write to different
        keys, so ior preserves all. If two nodes wrote the same key, the
        later update would overwrite (intended: one source per key).

    opinions: operator.add concatenates lists. Each judge appends its list of
        JudicialOpinions; nothing is overwritten, so all opinions are retained.
    """

    # Inputs (can be set directly or via Targeting Protocol from context_builder)
    repo_url: str
    pdf_path: str

    # Cached PDF conversion (set by pdf_preprocess so doc/vision don't convert in parallel)
    pdf_doc_context: dict  # {"path": str, "markdown": str, "chunks": list[str]}
    pdf_image_paths: list
    pdf_cleanup_path: str
    input: dict  # optional: { github_repo, pdf_report, pdf_images } for Targeting Protocol
    self_audit: bool  # optional: when True, report saved only to report_onself_generated (CLI --self-audit)

    # Loaded rubric and routed instructions (from ContextBuilder)
    rubric_dimensions: list[dict]
    forensic_instruction: str
    judicial_logic: str
    synthesis_rules: dict

    # Detective outputs: source -> list of Evidence
    evidences: Annotated[dict[str, list[Evidence]], operator.ior]

    # Judge outputs
    opinions: Annotated[list[JudicialOpinion], operator.add]

    # Synthesis and final output (last-wins reducer: when chief_justice runs multiple times in fan-in, keep last)
    criterion_results: Annotated[list[CriterionResult], _last_wins]
    final_report: Annotated[Optional[AuditReport], _last_wins]
