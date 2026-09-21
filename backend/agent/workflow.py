"""One check-pointed LangGraph workflow with explicit pause/resume branches."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Any
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from backend.agent.nodes import InvestigationAdapters, InvestigationNodes
from backend.agent.state import InvestigationState

def build_investigation_graph(adapters: InvestigationAdapters, checkpointer: Any):
    nodes = InvestigationNodes(adapters)
    graph = StateGraph(InvestigationState)
    for name in ("load_case", "validate_case_entities", "collect_graph_evidence", "retrieve_graphrag_context", "detect_patterns", "grade_evidence", "calculate_fraud_probability", "evaluate_stopping_criteria", "plan_evidence_request", "await_evidence", "apply_evidence_response", "apply_policy", "route_approvals", "persist_case", "finish"):
        graph.add_node(name, getattr(nodes, name))
    graph.add_edge(START, "load_case"); graph.add_edge("load_case", "validate_case_entities")
    graph.add_edge("validate_case_entities", "collect_graph_evidence"); graph.add_edge("collect_graph_evidence", "retrieve_graphrag_context")
    graph.add_edge("retrieve_graphrag_context", "detect_patterns"); graph.add_edge("detect_patterns", "grade_evidence")
    graph.add_edge("grade_evidence", "calculate_fraud_probability"); graph.add_edge("calculate_fraud_probability", "evaluate_stopping_criteria")
    graph.add_conditional_edges("evaluate_stopping_criteria", lambda state: "policy" if state.get("stop") else "evidence", {"policy": "apply_policy", "evidence": "plan_evidence_request"})
    graph.add_edge("plan_evidence_request", "await_evidence"); graph.add_edge("await_evidence", "apply_evidence_response")
    graph.add_edge("apply_evidence_response", "grade_evidence"); graph.add_edge("apply_policy", "route_approvals")
    graph.add_edge("route_approvals", "persist_case"); graph.add_edge("persist_case", "finish"); graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)

def sqlite_checkpointer(path: Path) -> SqliteSaver:
    """Persistent local development checkpointer; caller owns lifecycle/storage path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))
