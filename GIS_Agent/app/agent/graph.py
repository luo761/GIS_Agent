from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.deterministic import DeterministicGISAgent, PlannedToolCall
from app.agent.state import AgentState


def build_agent_graph(agent: DeterministicGISAgent | None = None):
    """Build a minimal LangGraph wrapper around the deterministic GIS agent."""

    gis_agent = agent or DeterministicGISAgent()

    def plan_node(state: AgentState) -> dict[str, Any]:
        plan = gis_agent.plan(state["question"])
        return {"plan": [call.__dict__ for call in plan], "error": None}

    def execute_node(state: AgentState) -> dict[str, Any]:
        plan = [
            PlannedToolCall(name=item["name"], arguments=item["arguments"])
            for item in state.get("plan", [])
        ]
        return {"tool_calls": gis_agent.execute_plan(plan), "error": None}

    def summarize_node(state: AgentState) -> dict[str, Any]:
        return {"answer": gis_agent.summarize(state["question"], state.get("tool_calls", []))}

    builder = StateGraph(AgentState)
    builder.add_node("plan", plan_node)
    builder.add_node("execute_tools", execute_node)
    builder.add_node("summarize", summarize_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "execute_tools")
    builder.add_edge("execute_tools", "summarize")
    builder.add_edge("summarize", END)
    return builder.compile()


def run_agent(question: str, agent: DeterministicGISAgent | None = None) -> AgentState:
    graph = build_agent_graph(agent)
    return graph.invoke({"question": question})
