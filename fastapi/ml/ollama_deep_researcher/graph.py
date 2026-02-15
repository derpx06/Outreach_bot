from typing import Any, AsyncGenerator, Dict, List

from langgraph.constants import Send
from langgraph.graph import END, StateGraph
from langsmith import traceable

from .configuration import Configuration
from .nodes import orchestrator, planner, research_worker, writer, publisher
from .state import AgentState


def route_research_or_end(state: AgentState) -> str:
    # If writer incremented index past the last section, we are done.
    outline = state.get("outline", [])
    index = state.get("current_section_index", 0)
    if index >= len(outline) and len(outline) > 0:
        return "publisher"
    return "research_worker"

workflow = StateGraph(AgentState)

# Nodes
workflow.add_node("orchestrator", orchestrator)
workflow.add_node("planner", planner)
workflow.add_node("research_worker", research_worker)
workflow.add_node("writer", writer)
workflow.add_node("publisher", publisher)

# Edges
workflow.set_entry_point("orchestrator")

# Orchestrator -> Planner (Skip research map, plan first)
workflow.add_edge("orchestrator", "planner")

# Planner -> Research (Start the loop)
workflow.add_edge("planner", "research_worker")

# Research -> Writer
workflow.add_edge("research_worker", "writer")

# Writer -> Conditional (Next Research or Publisher)
workflow.add_conditional_edges(
    "writer",
    route_research_or_end,
    {
        "research_worker": "research_worker",
        "publisher": "publisher"
    }
)

# Publisher -> End
workflow.add_edge("publisher", END)

graph = workflow.compile()


@traceable(name="Run Deep Research Writer")
async def run_deep_research(topic: str, config: Dict[str, Any] | None = None) -> AgentState:
    cfg = config or {}
    return await graph.ainvoke({"topic": topic}, config=cfg)


@traceable(name="Stream Deep Research Writer")
async def stream_deep_research(
    topic: str,
    config: Dict[str, Any] | None = None
) -> AsyncGenerator[Dict[str, Any], None]:
    cfg = config or {}
    async for event in graph.astream({"topic": topic}, config=cfg):
        yield event

if __name__ == "__main__":
    print(graph.get_graph().draw_mermaid())
