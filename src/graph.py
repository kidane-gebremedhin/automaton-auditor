# LangGraph Digital Courtroom: Detectives (parallel) -> EvidenceAggregator -> Judges (parallel) -> ChiefJustice -> END

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.config import configure_tracing
from src.nodes.context import context_builder
from src.nodes.detectives import doc_detective, pdf_preprocess, repo_detective, vision_inspector
from src.nodes.judges import defense, prosecutor, tech_lead
from src.nodes.justice import chief_justice, report_writer
from src.state import AgentState

configure_tracing()


# -----------------------------------------------------------------------------
# Routers (conditional edges): fan-out with Send
# -----------------------------------------------------------------------------


def detectives_router(state: AgentState) -> list[Send]:
    """Fan-out to Repo and/or PDF preprocess. PDF runs once then fans to doc+vision."""
    sends: list[Send] = []
    if state.get("repo_url"):
        sends.append(Send("repo_detective", state))
    if state.get("pdf_path"):
        sends.append(Send("pdf_preprocess", state))
    return sends


def after_pdf_preprocess_router(state: AgentState) -> list[Send]:
    """After single PDF conversion, fan-out to doc and optionally vision (req: execution optional)."""
    import os
    sends: list[Send] = [Send("doc_detective", state)]
    if os.environ.get("AUDITOR_SKIP_VISION", "").strip() not in ("1", "true", "yes"):
        sends.append(Send("vision_detective", state))
    return sends


def judges_router(state: AgentState) -> list[Send]:
    """Fan-out to Prosecutor, Defense, TechLead in parallel on identical evidence."""
    return [
        Send("prosecutor", state),
        Send("defense", state),
        Send("tech_lead", state),
    ]


def evidence_aggregator(state: AgentState) -> dict:
    """Fan-in: no-op; state already merged by reducers from parallel detectives."""
    return {}


def judges_aggregator(state: AgentState) -> dict:
    """Fan-in: no-op; state already merged by reducers from parallel judges. Ensures chief_justice runs once."""
    return {}


def no_input_handler(state: AgentState) -> dict:
    """When repo_url and pdf_path are both missing; set empty evidences and continue."""
    return {"evidences": {}}


# -----------------------------------------------------------------------------
# Build graph
# -----------------------------------------------------------------------------


def build_graph() -> StateGraph:
    """Build the complete StateGraph with parallel Detectives and Judges.

    FLOW:
      START -> (conditional) -> [repo_detective || doc_detective || vision_detective] (parallel)
           -> evidence_aggregator (fan-in)
           -> [prosecutor || defense || tech_lead] (parallel)
           -> chief_justice -> report_writer -> END

    Reducers (AgentState): evidences (operator.ior), opinions (operator.add).
    Missing PDF: doc_detective and vision_detective are not sent when pdf_path is missing.
    """
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("context_builder", context_builder)
    graph.add_node("repo_detective", repo_detective)
    graph.add_node("pdf_preprocess", pdf_preprocess)
    graph.add_node("doc_detective", doc_detective)
    graph.add_node("vision_detective", vision_inspector)
    graph.add_node("evidence_aggregator", evidence_aggregator)
    graph.add_node("prosecutor", prosecutor)
    graph.add_node("defense", defense)
    graph.add_node("tech_lead", tech_lead)
    graph.add_node("judges_aggregator", judges_aggregator)
    graph.add_node("chief_justice", chief_justice)
    graph.add_node("report_writer", report_writer)
    graph.add_node("no_input", no_input_handler)

    # START -> ContextBuilder (load rubric, route forensic_instruction/judicial_logic/synthesis_rules, apply Targeting)
    graph.add_edge(START, "context_builder")

    # ContextBuilder -> conditional fan-out to detectives or handle no input
    def start_route(state: AgentState) -> str | list[Send]:
        if not state.get("repo_url") and not state.get("pdf_path"):
            return "no_input"
        out = detectives_router(state)
        if not out:
            return "evidence_aggregator"
        return out

    graph.add_conditional_edges("context_builder", start_route)

    # Detectives -> EvidenceAggregator (fan-in)
    graph.add_edge("repo_detective", "evidence_aggregator")
    graph.add_conditional_edges("pdf_preprocess", after_pdf_preprocess_router)
    graph.add_edge("doc_detective", "evidence_aggregator")
    graph.add_edge("vision_detective", "evidence_aggregator")

    # no_input -> judges (need evidence_aggregator first for flow consistency; no_input goes to aggregator then judges)
    graph.add_edge("no_input", "evidence_aggregator")

    # EvidenceAggregator -> Judges (parallel fan-out)
    graph.add_conditional_edges("evidence_aggregator", judges_router)

    # Judges -> JudgesAggregator (fan-in) -> ChiefJustice (runs once)
    graph.add_edge("prosecutor", "judges_aggregator")
    graph.add_edge("defense", "judges_aggregator")
    graph.add_edge("tech_lead", "judges_aggregator")
    graph.add_edge("judges_aggregator", "chief_justice")

    # ChiefJustice -> Report -> END
    graph.add_edge("chief_justice", "report_writer")
    graph.add_edge("report_writer", END)

    return graph


def create_compiled_graph():
    """Compile the graph for invocation."""
    return build_graph().compile()
