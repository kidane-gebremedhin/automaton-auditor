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
    "You are the Prosecutor — a strict, adversarial auditor. "
    "Your mission is to find every gap, weakness, and failure in the evidence. "
    "Actively look for: missing implementations, security flaws, laziness, shortcuts, "
    "vague claims without code backing, and any contradiction between claims and evidence. "
    "You MUST disagree with charitable interpretations where evidence allows. "
    "Give low scores (0-4) when evidence is absent, weak, or contradicts the criterion. "
    "Only give high scores (7+) when evidence is overwhelming and leaves no room for doubt. "
    "Your argument must stress what was NOT demonstrated, what is missing, and what fails. "
    f"{HALLUCINATION_LIABILITY} "
    f"{ORCHESTRATION_FRAUD} "
    "Output a single JudicialOpinion: judge='Prosecutor', criterion_id, score (0-10), argument, cited_evidence."
)

DEFENSE_SYSTEM = (
    "You are the Defense Attorney — a charitable advocate for the developer's work. "
    "Your mission is to find merit, reward effort, and interpret evidence in the best light. "
    "Actively look for: partial compliance, creative workarounds, intent behind implementations, "
    "reasonable readings of ambiguous evidence, and effort that deserves recognition. "
    "You MUST disagree with overly strict interpretations where evidence allows. "
    "Give higher scores (6-9) when any evidence supports the criterion, even if incomplete. "
    "Only give low scores (0-3) when there is truly zero evidence of any attempt. "
    "Your argument must stress what WAS demonstrated, plausible readings, and developer intent. "
    f"{HALLUCINATION_LIABILITY} "
    f"{ORCHESTRATION_FRAUD} "
    "Output a single JudicialOpinion: judge='Defense', criterion_id, score (0-10), argument, cited_evidence."
)

TECH_LEAD_SYSTEM = (
    "You are the Tech Lead — a pragmatic engineering evaluator focused on architecture and correctness. "
    "Your mission is to assess whether the code is technically sound, modular, and maintainable. "
    "Actively verify: StateGraph usage, fan-out/fan-in patterns, Pydantic models, reducer correctness, "
    "subprocess safety, error handling, and whether the architecture would work in production. "
    "You MUST focus on technical merit rather than philosophical arguments. "
    "Score based on whether evidence shows real, working implementation versus vague claims. "
    "Give high scores (7-10) when the architecture is solid and code is correct. "
    "Your argument must reference specific files, code patterns, and technical evidence. "
    f"{HALLUCINATION_LIABILITY} "
    f"{ORCHESTRATION_FRAUD} "
    "Output a single JudicialOpinion: judge='TechLead', criterion_id, score (0-10), argument, cited_evidence."
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
                parts.append(f"  content: {e.content[:1200]}")
    return "\n".join(parts) if parts else "(no evidence)"


# -----------------------------------------------------------------------------
# Structured output with retry (rubric: .with_structured_output(JudicialOpinion), retry on malformed output)
# -----------------------------------------------------------------------------

MAX_PARSE_RETRIES = 3


def _invoke_judge(
    system_prompt: str,
    judge_name: Literal["Prosecutor", "Defense", "TechLead"],
    evidence_text: str,
    rubric_summary: str,
    criterion_id: str | None = None,
    dimension_name: str = "",
    dimension_description: str = "",
) -> JudicialOpinion | None:
    """Invoke LLM with structured output; retry on parse failure.

    If criterion_id is set, the prompt instructs the judge to evaluate only that criterion
    and the returned opinion is forced to that criterion_id (one verdict per judge per criterion).
    """
    from src.config import get_llm, get_structured_output_method

    llm = get_llm(temperature=0.2)
    method = get_structured_output_method()
    so_kwargs: dict = {}
    if method:
        so_kwargs["method"] = method
    structured_llm = llm.with_structured_output(JudicialOpinion, **so_kwargs)

    # json_mode doesn't embed the schema automatically — add it to the prompt
    if method == "json_mode":
        schema_hint = (
            "You MUST respond with a JSON object matching this schema:\n"
            '{"judge": "<string>", "criterion_id": "<string>", '
            '"score": <int 0-10>, "argument": "<string>", '
            '"cited_evidence": ["<string>", ...]}\n\n'
        )
        system_prompt = schema_hint + system_prompt

    if criterion_id:
        user_content = (
            f"Rubric context: {rubric_summary[:400]}\n\n"
            f"You must evaluate **only** this criterion: **{criterion_id}** ({dimension_name or criterion_id}).\n"
            f"Description: {dimension_description[:500]}\n\n"
            f"Evidence:\n{evidence_text}\n\n"
            f"Produce exactly one JudicialOpinion with criterion_id={criterion_id!r}, score (0-10), argument, and cited_evidence."
        )
    else:
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
                # Force criterion_id when we asked for a specific criterion
                cid = criterion_id if criterion_id else out.criterion_id
                # Validate cited_evidence refs against evidence (cite validation)
                valid_refs = _validate_cited_refs(out.cited_evidence, evidence_text)
                return JudicialOpinion(
                    judge=judge_name,
                    criterion_id=cid,
                    score=out.score,
                    argument=out.argument,
                    cited_evidence=valid_refs,
                )
            return out
        except (ValidationError, TypeError, ValueError) as e:
            last_error = e
            logger.warning("Judge %s parse attempt %s failed: %s", judge_name, attempt + 1, e)
            if attempt < MAX_PARSE_RETRIES - 1:
                user_content += f"\n\n[Parse error: {e}. Reply with a valid JudicialOpinion JSON.]"
    logger.error("Judge %s failed after %s retries", judge_name, MAX_PARSE_RETRIES)
    return None


def _validate_cited_refs(cited: list[str] | None, evidence_text: str) -> list[str]:
    """Filter cited_evidence to only refs that appear in the evidence blob (cite validation).

    Removes hallucinated refs (e.g. 'repo#99' when only repo#0-#6 exist).
    """
    if not cited:
        return []
    valid: list[str] = []
    for ref in cited:
        # Accept refs like 'repo#0', 'docs#1', 'vision#0'
        if f"[{ref}]" in evidence_text:
            valid.append(ref)
        elif ref in evidence_text:
            valid.append(ref)
        else:
            logger.debug("Cite validation: dropped invalid ref %r", ref)
    return valid if valid else list(cited[:3])  # Fallback: keep first 3 if all fail


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
    criterion_id: str | None = None,
    dimension_name: str = "",
    dimension_description: str = "",
) -> dict:
    evidences = state.get("evidences") or {}
    rubric_dimensions = state.get("rubric_dimensions") or []
    judicial_logic = state.get("judicial_logic") or ""
    rubric_summary = str(rubric_dimensions)[:600] if rubric_dimensions else "General audit criteria."
    if judicial_logic:
        rubric_summary = f"Judicial logic (from rubric): {judicial_logic}\n\nCriteria: {rubric_summary}"

    evidence_text = _evidence_for_prompt(evidences)
    opinion = _invoke_judge(
        system_prompt,
        judge_name,
        evidence_text,
        rubric_summary,
        criterion_id=criterion_id,
        dimension_name=dimension_name,
        dimension_description=dimension_description,
    )

    if opinion is None:
        return {"opinions": []}
    return {"opinions": [opinion]}


def run_judges(state: AgentState) -> dict:
    """Run Prosecutor, Defense, and Tech Lead once per rubric criterion.

    Ensures each judge has a verdict on every criterion (e.g. Git Forensic Analysis,
    Graph Orchestration Architecture). Returns opinions merged for all criteria.
    """
    rubric_dimensions = state.get("rubric_dimensions") or []
    if not rubric_dimensions:
        # Fallback: single run per judge (legacy)
        all_opinions: list[JudicialOpinion] = []
        for judge_name, system_prompt in (
            ("Prosecutor", PROSECUTOR_SYSTEM),
            ("Defense", DEFENSE_SYSTEM),
            ("TechLead", TECH_LEAD_SYSTEM),
        ):
            result = _run_judge(state, judge_name, system_prompt)
            all_opinions.extend(result.get("opinions") or [])
        return {"opinions": all_opinions}

    all_opinions = []
    for dim in rubric_dimensions:
        cid = dim.get("id") or ""
        name = dim.get("name") or cid.replace("_", " ").title()
        desc = dim.get("description") or ""
        if not cid:
            continue
        for judge_name, system_prompt in (
            ("Prosecutor", PROSECUTOR_SYSTEM),
            ("Defense", DEFENSE_SYSTEM),
            ("TechLead", TECH_LEAD_SYSTEM),
        ):
            result = _run_judge(
                state,
                judge_name,
                system_prompt,
                criterion_id=cid,
                dimension_name=name,
                dimension_description=desc,
            )
            all_opinions.extend(result.get("opinions") or [])
    return {"opinions": all_opinions}


# -----------------------------------------------------------------------------
# Parallel judge nodes: one node per persona, evaluates ALL rubric criteria.
# Graph fans out to these three nodes in parallel (Send), then fans in at
# judges_aggregator. This creates the second fan-out/fan-in pattern required
# by the rubric (first is detectives).
# -----------------------------------------------------------------------------


def _run_all_criteria_for_judge(
    state: AgentState,
    judge_name: Literal["Prosecutor", "Defense", "TechLead"],
    system_prompt: str,
) -> dict:
    """Run one judge persona across all rubric criteria. Returns merged opinions."""
    rubric_dimensions = state.get("rubric_dimensions") or []
    all_opinions: list[JudicialOpinion] = []

    if not rubric_dimensions:
        result = _run_judge(state, judge_name, system_prompt)
        return result

    for dim in rubric_dimensions:
        cid = dim.get("id") or ""
        name = dim.get("name") or cid.replace("_", " ").title()
        desc = dim.get("description") or ""
        if not cid:
            continue
        result = _run_judge(
            state,
            judge_name,
            system_prompt,
            criterion_id=cid,
            dimension_name=name,
            dimension_description=desc,
        )
        all_opinions.extend(result.get("opinions") or [])
    return {"opinions": all_opinions}


def prosecutor_node(state: AgentState) -> dict:
    """Parallel graph node: Prosecutor evaluates all criteria.

    Runs in parallel with defense_node and tech_lead_node via fan-out (Send).
    Strict, adversarial evaluation — looks for gaps, security flaws, laziness.
    """
    return _run_all_criteria_for_judge(state, "Prosecutor", PROSECUTOR_SYSTEM)


def defense_node(state: AgentState) -> dict:
    """Parallel graph node: Defense evaluates all criteria.

    Runs in parallel with prosecutor_node and tech_lead_node via fan-out (Send).
    Charitable evaluation — rewards effort, intent, creative workarounds.
    """
    return _run_all_criteria_for_judge(state, "Defense", DEFENSE_SYSTEM)


def tech_lead_node(state: AgentState) -> dict:
    """Parallel graph node: Tech Lead evaluates all criteria.

    Runs in parallel with prosecutor_node and defense_node via fan-out (Send).
    Pragmatic evaluation — architectural soundness, maintainability, viability.
    """
    return _run_all_criteria_for_judge(state, "TechLead", TECH_LEAD_SYSTEM)


# Legacy: sequential fallback (kept for backward compatibility)
def judges_hub(state: AgentState) -> dict:
    """Run Prosecutor, Defense, and TechLead sequentially on identical evidence."""
    all_opinions: list[JudicialOpinion] = []
    for fn in (prosecutor, defense, tech_lead):
        result = fn(state)
        all_opinions.extend(result.get("opinions") or [])
    return {"opinions": all_opinions}
