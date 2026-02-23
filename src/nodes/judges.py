"""Judge nodes: Prosecutor, Defense, Tech Lead."""

from src.state import AgentState, JudicialOpinion


def judges_hub(state: AgentState) -> dict:
    """Hub: dispatch to Prosecutor, Defense, Tech Lead; merge opinions.

    TODO: Use LangGraph parallel/send_all for true fan-out/fan-in.
    """
    # Placeholder: return empty opinions
    return {"opinions": []}


def run_prosecutor(state: AgentState) -> dict:
    """Prosecutor judge: critical lens on rubric criteria.

    TODO: Use LLM with rubric to evaluate evidence, produce JudicialOpinion
    per criterion with verdict (PASS/FAIL/PARTIAL) and structured JSON output.
    """
    # TODO: LLM call with rubric + evidences, structured output as JudicialOpinion
    return {"opinions": []}


def run_defense(state: AgentState) -> dict:
    """Defense judge: sympathetic lens on rubric criteria.

    TODO: Use LLM with rubric to evaluate evidence from defense perspective,
    produce JudicialOpinion per criterion.
    """
    # TODO: LLM call with rubric + evidences, structured output as JudicialOpinion
    return {"opinions": []}


def run_tech_lead(state: AgentState) -> dict:
    """Tech Lead judge: technical rigor lens on rubric criteria.

    TODO: Use LLM with rubric to evaluate evidence with technical focus,
    produce JudicialOpinion per criterion.
    """
    # TODO: LLM call with rubric + evidences, structured output as JudicialOpinion
    return {"opinions": []}


def run_judges(state: AgentState) -> dict:
    """Fan-in: run all judges in parallel and merge opinions.

    TODO: Parallel execution of Prosecutor, Defense, Tech Lead; merge
    opinions into state. Ensure structured JSON output per rubric.
    """
    # TODO: parallel dispatch, merge opinions
    pro = run_prosecutor(state)
    def_ = run_defense(state)
    tech = run_tech_lead(state)
    opinions = (
        pro.get("opinions", [])
        + def_.get("opinions", [])
        + tech.get("opinions", [])
    )
    return {"opinions": opinions}
