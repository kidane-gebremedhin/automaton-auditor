# LangGraph Digital Courtroom: Detectives (parallel) -> EvidenceAggregator -> Judges (parallel) -> ChiefJustice -> END
#
# Graph structure (rubric): START -> [Detectives in parallel] -> EvidenceAggregator -> [Judges in parallel] -> ChiefJustice -> END.
# Fan-out #1 (Detectives): context_builder -> detectives_router (Send to repo_detective, pdf_preprocess);
#   pdf_preprocess -> doc_detective + vision_detective.
# Fan-in #1: repo_detective, doc_detective, vision_detective -> evidence_aggregator.
# Fan-out #2 (Judges): evidence_aggregator -> judges_router (Send to prosecutor_node, defense_node, tech_lead_node).
# Fan-in #2: prosecutor_node, defense_node, tech_lead_node -> judges_aggregator.
# Then: judges_aggregator -> chief_justice -> report_writer -> END.
# Conditional edges handle routing and optional vision; error states are handled by node try/except and evidence found=False.

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.config import configure_tracing
from src.nodes.context import context_builder
from src.nodes.detectives import doc_detective, pdf_preprocess, repo_detective, vision_inspector
from src.nodes.judges import defense_node, prosecutor_node, tech_lead_node
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
    """Fan-out #2: send evidence to all three judge nodes in parallel (Prosecutor, Defense, Tech Lead).

    Each judge node evaluates all rubric criteria from its distinct persona.
    This creates the second fan-out/fan-in pattern (first is detectives).
    """
    return [
        Send("prosecutor_node", state),
        Send("defense_node", state),
        Send("tech_lead_node", state),
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
    """Build the complete StateGraph with TWO parallel fan-out/fan-in patterns.

    FLOW (two distinct fan-out/fan-in patterns):
      START -> context_builder
        -> (conditional fan-out #1) -> [repo_detective || doc_detective || vision_detective] (parallel)
        -> evidence_aggregator (fan-in #1)
        -> (fan-out #2) -> [prosecutor_node || defense_node || tech_lead_node] (parallel)
        -> judges_aggregator (fan-in #2)
        -> chief_justice -> report_writer -> END

    Fan-out #1 (Detectives): context_builder -> Send(repo_detective), Send(pdf_preprocess -> doc/vision).
    Fan-in #1: All detectives -> evidence_aggregator (state merged by operator.ior on evidences).
    Fan-out #2 (Judges): evidence_aggregator -> Send(prosecutor_node, defense_node, tech_lead_node).
    Fan-in #2: All judges -> judges_aggregator (state merged by operator.add on opinions).
    """
    graph = StateGraph(AgentState)

    # Nodes — Detective layer
    graph.add_node("context_builder", context_builder)
    graph.add_node("repo_detective", repo_detective)
    graph.add_node("pdf_preprocess", pdf_preprocess)
    graph.add_node("doc_detective", doc_detective)
    graph.add_node("vision_detective", vision_inspector)
    graph.add_node("evidence_aggregator", evidence_aggregator)

    # Nodes — Judge layer (parallel: three distinct personas)
    graph.add_node("prosecutor_node", prosecutor_node)
    graph.add_node("defense_node", defense_node)
    graph.add_node("tech_lead_node", tech_lead_node)

    # Nodes — Synthesis layer
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

    # no_input -> judges (need evidence_aggregator first for flow consistency)
    graph.add_edge("no_input", "evidence_aggregator")

    # EvidenceAggregator -> [Judges in parallel] (fan-out #2: Send to prosecutor, defense, tech_lead)
    graph.add_conditional_edges("evidence_aggregator", judges_router)

    # Judges -> JudgesAggregator (fan-in #2)
    graph.add_edge("prosecutor_node", "judges_aggregator")
    graph.add_edge("defense_node", "judges_aggregator")
    graph.add_edge("tech_lead_node", "judges_aggregator")

    # JudgesAggregator -> ChiefJustice -> Report -> END
    graph.add_edge("judges_aggregator", "chief_justice")

    # ChiefJustice -> Report -> END
    graph.add_edge("chief_justice", "report_writer")
    graph.add_edge("report_writer", END)

    return graph


def create_compiled_graph():
    """Compile the graph for invocation."""
    return build_graph().compile()
