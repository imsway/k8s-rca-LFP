from langgraph.graph import END, START, StateGraph

from src.agent.nodes import investigate_node, route_after_investigate, synthesize_node, triage_node
from src.agent.state import InvestigationState


def build_graph():
    graph = StateGraph(InvestigationState)
    graph.add_node("triage", triage_node)
    graph.add_node("investigate", investigate_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "investigate")
    graph.add_conditional_edges(
        "investigate", route_after_investigate, {"investigate": "investigate", "synthesize": "synthesize"}
    )
    graph.add_edge("synthesize", END)

    return graph.compile()
