"""Detective nodes: RepoInvestigator, DocAnalyst, VisionInspector."""

from src.state import AgentState, Evidence


def detectives_hub(state: AgentState) -> dict:
    """Hub: dispatch to RepoInvestigator, DocAnalyst, VisionInspector; merge evidences."""
    evidences: dict = {}
    if state.get("repo_url"):
        evidences.update(run_repo_investigator(state).get("evidences", {}))
    if state.get("pdf_path"):
        evidences.update(run_doc_analyst(state).get("evidences", {}))
    return {"evidences": evidences}


def run_repo_investigator(state: AgentState) -> dict:
    """Run RepoInvestigator: clone repo and populate evidences["repo"]."""
    from src.tools.repo_investigator import repo_investigator_main

    return repo_investigator_main(state)


def run_doc_analyst(state: AgentState) -> dict:
    """Run DocAnalyst: parse PDF and populate evidences["docs"]."""
    from src.tools.doc_analyst import doc_analyst_main

    return doc_analyst_main(state)


def run_vision_inspector(state: AgentState) -> dict:
    """Run VisionInspector detective (optional image/screenshot analysis).

    TODO: Invoke src.tools.vision_inspector for multimodal analysis if applicable.
    """
    # TODO: analyze images/figures from PDF or repo, return Evidence
    return {"evidences": {"VisionInspector": []}}


def run_detectives(state: AgentState) -> dict:
    """Fan-in: run all detectives and merge evidences (for use by detectives_hub).

    TODO: Use LangGraph's parallel node execution or send_all to run
    RepoInvestigator, DocAnalyst, VisionInspector concurrently.
    """
    repo_ev = run_repo_investigator(state)
    doc_ev = run_doc_analyst(state)
    vis_ev = run_vision_inspector(state)
    evidences = {}
    for d in (repo_ev, doc_ev, vis_ev):
        evidences.update(d.get("evidences", {}))
    return {"evidences": evidences}
