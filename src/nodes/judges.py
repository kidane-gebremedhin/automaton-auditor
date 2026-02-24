"""Judges: Prosecutor, Defense, TechLead with structured output.

All judges run in parallel on identical evidence. Enforce Hallucination Liability
and Orchestration Fraud rules. Retry on parse failure.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import ValidationError

from src.state import AgentState, Evidence, JudicialOpinion

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Rules (enforced in every judge prompt)
# -----------------------------------------------------------------------------

HALLUCINATION_LIABILITY = (
    "Hallucination Liability: Cite only evidence that appears in the provided evidence list. "
    "Each cited_evidence entry must match a goal/location or content snippet from the evidence. "
    "Do not invent file paths, quotes, or findings."
)

ORCHESTRATION_FRAUD = (
    "Orchestration Fraud: Do not claim parallel execution, fan-out, or fan-in unless "
    "the evidence explicitly supports it (e.g. graph structure analysis, diagram classification). "
    "If evidence is silent, say so."
)

# -----------------------------------------------------------------------------
# Distinct system prompts (< 50% overlap)
# -----------------------------------------------------------------------------

PROSECUTOR_SYSTEM = (
    "You are the Prosecutor. Your role is to evaluate the audit evidence with strict, critical standards. "
    "Emphasize gaps, missing evidence, and failures to meet requirements. "
    "Give low scores when evidence is absent or weak. "
    "Your argument must stress what was not demonstrated or what contradicts the claims. "
    f"{HALLUCINATION_LIABILITY} "
    f"{ORCHESTRATION_FRAUD} "
    "Output a single JudicialOpinion: judge='Prosecutor', criterion_id, score (0-10), argument, cited_evidence (list of short refs from the evidence)."
)

DEFENSE_SYSTEM = (
    "You are the Defense. Your role is to interpret the audit evidence charitably and highlight what was achieved. "
    "Emphasize partial compliance, reasonable interpretations, and benefit of the doubt. "
    "Give higher scores when any evidence supports the criterion, even if incomplete. "
    "Your argument must stress what was demonstrated and plausible readings of the evidence. "
    f"{HALLUCINATION_LIABILITY} "
    f"{ORCHESTRATION_FRAUD} "
    "Output a single JudicialOpinion: judge='Defense', criterion_id, score (0-10), argument, cited_evidence (list of short refs from the evidence)."
)

TECH_LEAD_SYSTEM = (
    "You are the Tech Lead. Your role is to evaluate technical correctness and architecture. "
    "Focus on state management, graph orchestration, code structure, and correctness of claims. "
    "Score based on whether the evidence shows real implementation (e.g. StateGraph, fan-out) or vague claims. "
    "Your argument must reference specific technical evidence (files, structure, diagrams). "
    f"{HALLUCINATION_LIABILITY} "
    f"{ORCHESTRATION_FRAUD} "
    "Output a single JudicialOpinion: judge='TechLead', criterion_id, score (0-10), argument, cited_evidence (list of short refs from the evidence)."
)

# -----------------------------------------------------------------------------
# Evidence serialization for prompt
# -----------------------------------------------------------------------------


def _evidence_for_prompt(evidences: dict[str, list[Evidence]]) -> str:
    """Serialize state.evidences for the LLM (identical input for all judges)."""
    parts: list[str] = []
    for source, items in (evidences or {}).items():
        for i, e in enumerate(items):
            parts.append(
                f"[{source}#{i}] goal={e.goal!r} found={e.found} location={e.location!r} "
                f"rationale={e.rationale!r} confidence={e.confidence}"
            )
            if e.content:
                parts.append(f"  content: {e.content[:500]}")
    return "\n".join(parts) if parts else "(no evidence)"


# -----------------------------------------------------------------------------
# Structured output with retry
# -----------------------------------------------------------------------------

MAX_PARSE_RETRIES = 3


def _invoke_judge(
    system_prompt: str,
    judge_name: Literal["Prosecutor", "Defense", "TechLead"],
    evidence_text: str,
    rubric_summary: str,
) -> JudicialOpinion | None:
    """Invoke LLM with structured output; retry on parse failure."""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    structured_llm = llm.with_structured_output(JudicialOpinion)

    user_content = (
        f"Rubric (summary): {rubric_summary}\n\n"
        f"Evidence (identical for all judges):\n{evidence_text}\n\n"
        "Produce one JudicialOpinion with score (0-10), argument, and cited_evidence."
    )

    last_error: Exception | None = None
    for attempt in range(MAX_PARSE_RETRIES):
        try:
            out = structured_llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]
            )
            if isinstance(out, JudicialOpinion):
                # Ensure judge field matches
                return JudicialOpinion(
                    judge=judge_name,
                    criterion_id=out.criterion_id,
                    score=out.score,
                    argument=out.argument,
                    cited_evidence=out.cited_evidence or [],
                )
            return out
        except (ValidationError, TypeError, ValueError) as e:
            last_error = e
            logger.warning("Judge %s parse attempt %s failed: %s", judge_name, attempt + 1, e)
            if attempt < MAX_PARSE_RETRIES - 1:
                user_content += f"\n\n[Parse error: {e}. Reply with a valid JudicialOpinion JSON.]"
    logger.error("Judge %s failed after %s retries", judge_name, MAX_PARSE_RETRIES)
    return None


# -----------------------------------------------------------------------------
# Judge nodes (same state = identical evidence)
# -----------------------------------------------------------------------------


def prosecutor(state: AgentState) -> dict:
    """Prosecutor: critical evaluation. Runs on same evidence as Defense and TechLead."""
    return _run_judge(state, "Prosecutor", PROSECUTOR_SYSTEM)


def defense(state: AgentState) -> dict:
    """Defense: charitable evaluation. Runs on same evidence as Prosecutor and TechLead."""
    return _run_judge(state, "Defense", DEFENSE_SYSTEM)


def tech_lead(state: AgentState) -> dict:
    """Tech Lead: technical evaluation. Runs on same evidence as Prosecutor and Defense."""
    return _run_judge(state, "TechLead", TECH_LEAD_SYSTEM)


def _run_judge(
    state: AgentState,
    judge_name: Literal["Prosecutor", "Defense", "TechLead"],
    system_prompt: str,
) -> dict:
    evidences = state.get("evidences") or {}
    rubric_dimensions = state.get("rubric_dimensions") or []
    judicial_logic = state.get("judicial_logic") or ""
    rubric_summary = str(rubric_dimensions)[:600] if rubric_dimensions else "General audit criteria."
    if judicial_logic:
        rubric_summary = f"Judicial logic (from rubric): {judicial_logic}\n\nCriteria: {rubric_summary}"

    evidence_text = _evidence_for_prompt(evidences)
    opinion = _invoke_judge(system_prompt, judge_name, evidence_text, rubric_summary)

    if opinion is None:
        return {"opinions": []}
    return {"opinions": [opinion]}


# -----------------------------------------------------------------------------
# Parallel hub: run all judges on identical evidence
# -----------------------------------------------------------------------------


def judges_hub(state: AgentState) -> dict:
    """Run Prosecutor, Defense, and TechLead on identical evidence.

    All three receive the same state (evidences, rubric). Opinions are merged
    via state reducer (operator.add). For true concurrency, wire the graph
    to fan-out to prosecutor/defense/tech_lead nodes and fan-in to the next step.
    """
    all_opinions: list[JudicialOpinion] = []
    for fn in (prosecutor, defense, tech_lead):
        result = fn(state)
        all_opinions.extend(result.get("opinions") or [])
    return {"opinions": all_opinions}
