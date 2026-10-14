"""Builds the LangGraph research workflow.

The graph wires the six agents into an explicit state machine with real
conditional routing and bounded retry loops. It is compiled with a SQLite
checkpointer when available so partial progress survives a restart.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from langgraph.graph import END, START, StateGraph

from app.agents.context import AgentContext
from app.config import Settings
from app.graph.nodes import Nodes
from app.graph.recorder import NullRecorder, RunRecorder
from app.graph.state import ResearchState

logger = logging.getLogger(__name__)

_checkpointer = None


def get_checkpointer(settings: Settings):
    """Return a shared SQLite checkpointer, or None if unavailable.

    A single connection is reused for the process lifetime. Checkpointing is
    best-effort: if setup fails the graph still runs in-memory.
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        path = Path("data/checkpoints.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        saver = SqliteSaver(conn)
        setup = getattr(saver, "setup", None)
        if callable(setup):
            setup()
        _checkpointer = saver
        logger.info("LangGraph checkpointer ready at %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Checkpointing disabled (checkpointer unavailable): %s", exc)
        _checkpointer = False  # sentinel: tried and failed
    return _checkpointer or None


def build_graph(
    context: AgentContext,
    recorder: Optional[RunRecorder] = None,
    checkpointer=None,
):
    """Compile the research workflow graph."""
    nodes = Nodes(context, recorder or NullRecorder())

    graph = StateGraph(ResearchState)

    graph.add_node("validate", nodes.validate)
    graph.add_node("plan", nodes.plan)
    graph.add_node("research", nodes.research)
    graph.add_node("verify", nodes.verify)
    graph.add_node("followup", nodes.followup)
    graph.add_node("analyze", nodes.analyze)
    graph.add_node("write", nodes.write)
    graph.add_node("review", nodes.review)
    graph.add_node("revise", nodes.revise)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "validate")
    graph.add_conditional_edges(
        "validate", nodes.route_after_validate, {"plan": "plan", "end": END}
    )
    graph.add_conditional_edges(
        "plan", nodes.route_after_plan, {"research": "research", "end": END}
    )
    graph.add_edge("research", "verify")
    graph.add_conditional_edges(
        "verify", nodes.route_evidence, {"followup": "followup", "analyze": "analyze"}
    )
    graph.add_edge("followup", "research")
    graph.add_edge("analyze", "write")
    graph.add_edge("write", "review")
    graph.add_conditional_edges(
        "review", nodes.route_review, {"revise": "revise", "finalize": "finalize"}
    )
    graph.add_edge("revise", "write")
    graph.add_edge("finalize", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


def graph_thread_config(research_id: str) -> dict:
    """Return the LangGraph config binding a run to its checkpoint thread."""
    return {"configurable": {"thread_id": research_id}, "recursion_limit": 50}


MERMAID_DIAGRAM = """\
flowchart TD
    START([START]) --> validate[Validate question]
    validate -->|invalid| END1([END])
    validate -->|valid| plan[Coordinator: create research plan]
    plan -->|error| END1
    plan --> research[Research agent: search + fetch]
    research --> verify[Evidence agent: verify claims]
    verify --> decision{Evidence sufficient?}
    decision -->|no, retries left| followup[Generate targeted follow-up]
    followup --> research
    decision -->|yes / retries exhausted| analyze[Analysis agent: synthesize]
    analyze --> write[Report writer: generate report]
    write --> review[Reviewer: check report]
    review --> decision2{Report passes?}
    decision2 -->|no, retries left| revise[Incorporate feedback]
    revise --> write
    decision2 -->|yes / retries exhausted| finalize[Finalize + save]
    finalize --> END2([END])
"""
