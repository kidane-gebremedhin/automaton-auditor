"""Chief Justice and report writer."""

from src.state import AgentState


def chief_justice(state: AgentState) -> dict:
    """Chief Justice: synthesize Prosecutor, Defense, Tech Lead opinions.

    TODO: Apply deterministic synthesis rules (e.g. majority vote, weighted
    by rubric, or explicit rules from constitution) to produce final
    verdicts per criterion. Output synthesis dict with criterion_id -> verdict.
    """
    # TODO: Load rubric, apply synthesis rules to opinions,
    # produce synthesis: dict[str, dict] with final verdict + rationale
    return {}


def report_writer(state: AgentState) -> dict:
    """Generate final Markdown Audit Report.

    Sections:
      - Executive Summary
      - Criterion Breakdown (per rubric)
      - Remediation Plan

    TODO: Use synthesis + evidences + opinions to build structured markdown.
    """
    # TODO: Build markdown from synthesis, evidences, opinions
    return {"final_report": "# Audit Report\n\n*TODO*"}
