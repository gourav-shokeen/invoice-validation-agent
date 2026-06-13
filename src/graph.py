from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import extract, finalize, flag, ingest, validate
from .state import AgentState

# extraction attempts before flagging
MAX_ATTEMPTS = 2


def route_after_validate(state: AgentState) -> str:
    if not state.get("validation_errors"):
        return "finalize"
    if state.get("attempts", 0) < MAX_ATTEMPTS:
        return "extract"
    return "flag"


def build_graph():
    """Build and compile the invoice-validation state machine."""
    graph = StateGraph(AgentState)

    graph.add_node("ingest", ingest)
    graph.add_node("extract", extract)
    graph.add_node("validate", validate)
    graph.add_node("finalize", finalize)
    graph.add_node("flag", flag)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "extract")
    graph.add_edge("extract", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {"finalize": "finalize", "extract": "extract", "flag": "flag"},
    )
    graph.add_edge("finalize", END)
    graph.add_edge("flag", END)

    return graph.compile()
