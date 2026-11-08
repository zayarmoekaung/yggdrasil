"""LangGraph state graph for the DM Agent round lifecycle."""

from typing import Any

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from aetherdm.models import ActionPool, DMResolution


class DMState(TypedDict):
    """State for the DM Agent graph."""
    pool: ActionPool
    location_context: dict[str, Any]
    character_context: list[dict[str, Any]]
    resolution: DMResolution | None
    narrative: str


def gather_context(state: DMState) -> DMState:
    """Node: gather and format context (done externally by DMAgent.build_context)."""
    # This node is a placeholder — context is pre-built by the engine.
    return state


def resolve_actions(state: DMState) -> DMState:
    """Node: call LLM to resolve actions (done externally by DMAgent.resolve_pool)."""
    # This node is a placeholder — resolution is done by the DMAgent.
    return state


def emit_effects(state: DMState) -> DMState:
    """Node: convert resolution to Effects (done by DMAgent.resolution_to_effects)."""
    return state


def generate_narrative(state: DMState) -> DMState:
    """Node: extract narrative from resolution."""
    if state.get("resolution"):
        state["narrative"] = state["resolution"].narrative
    return state


def build_dm_graph() -> StateGraph:
    """Build the LangGraph state graph for DM resolution.

    Phase 2: The graph is a simple linear flow.
    Later phases will add branching, NPC agent nodes, etc.
    """
    graph = StateGraph(DMState)

    graph.add_node("gather_context", gather_context)
    graph.add_node("resolve_actions", resolve_actions)
    graph.add_node("emit_effects", emit_effects)
    graph.add_node("generate_narrative", generate_narrative)

    graph.set_entry_point("gather_context")
    graph.add_edge("gather_context", "resolve_actions")
    graph.add_edge("resolve_actions", "emit_effects")
    graph.add_edge("emit_effects", "generate_narrative")
    graph.add_edge("generate_narrative", END)

    return graph.compile()
