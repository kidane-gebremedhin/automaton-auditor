"""LangGraph Digital Courtroom - main graph definition."""

from pathlib import Path

from langgraph.graph import END, StateGraph

import src.config  # noqa: F401 - loads .env, enables LangSmith tracing

from src.nodes.context import context_builder
from src.nodes.detectives import detectives_hub
from src.nodes.judges import judges_hub
from src.nodes.justice import chief_justice, report_writer
from src.state import AgentState


def build_graph(rubric_path: str | Path = "rubric/week2_rubric.json") -> StateGraph:
    """Build the Digital Courtroom LangGraph.

    Topology:
        START -> context_builder -> detectives_hub -> judges_hub
             -> chief_justice -> report_writer -> END
    """
    graph = StateGraph(AgentState)

    graph.add_node("context_builder", context_builder)
    graph.add_node("detectives_hub", detectives_hub)
    graph.add_node("judges_hub", judges_hub)
    graph.add_node("chief_justice", chief_justice)
    graph.add_node("report_writer", report_writer)

    graph.add_edge("__start__", "context_builder")
    graph.add_edge("context_builder", "detectives_hub")
    graph.add_edge("detectives_hub", "judges_hub")
    graph.add_edge("judges_hub", "chief_justice")
    graph.add_edge("chief_justice", "report_writer")
    graph.add_edge("report_writer", END)

    return graph


def create_compiled_graph(rubric_path: str | Path = "rubric/week2_rubric.json"):
    """Create and compile the graph for execution."""
    return build_graph(rubric_path).compile()
