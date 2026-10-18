"""LangGraph reasoning subgraphs (PRODUCT_SPEC §4, §7).

An agent is a small, bounded graph with typed input and output:

    prepare -> generate (model gateway; validated JSON, one repair) -> post_validate (deterministic checks) -> END

It has no tools beyond what its graph defines, cannot reach the network except through the gateway, and only
proposes artifacts/next actions; the API and Temporal policy layer decide what is committed. The checkpointer
records each node's state within the activity; the gateway's idempotent invocation cache makes a retried
activity replay the same model answer without re-billing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ..gateway import ModelCall, ModelGateway, ModelResult


class AgentState(TypedDict, total=False):
    """Checkpointed state: JSON-serializable values only."""

    inputs: dict[str, Any]
    prompt: dict[str, Any]
    raw_output: dict[str, Any]
    provenance: dict[str, Any]
    output: dict[str, Any]
    problems: list[str]
    trace: list[str]


@dataclass
class AgentSpec:
    name: str
    prompt_version: str
    output_model: type[BaseModel]
    build_call: Callable[[dict[str, Any]], ModelCall]
    post_validate: Callable[[dict[str, Any], BaseModel], tuple[dict[str, Any], list[str]]] | None = None
    allowed_tools: list[str] = field(default_factory=list)


@dataclass
class AgentRun:
    output: dict[str, Any]
    problems: list[str]
    provenance: dict[str, Any]
    trace: list[str]


def build_graph(spec: AgentSpec, gateway: ModelGateway, scope: str):
    async def prepare(state: AgentState) -> AgentState:
        call = spec.build_call(state["inputs"])
        return {"prompt": {"agent": call.agent, "prompt_version": call.prompt_version,
                           "data_classification": call.data_classification, "max_tokens": call.max_tokens,
                           "user_chars": len(call.user)},
                "trace": [f"{spec.name}:prepare"]}

    async def generate(state: AgentState) -> AgentState:
        result: ModelResult = await gateway.generate(spec.build_call(state["inputs"]), scope)
        return {"raw_output": result.output.model_dump(mode="json"), "provenance": result.provenance(),
                "trace": [*state.get("trace", []), f"{spec.name}:generate"]}

    async def post_validate(state: AgentState) -> AgentState:
        parsed = spec.output_model.model_validate(state["raw_output"])
        if spec.post_validate is None:
            out, problems = parsed.model_dump(mode="json"), []
        else:
            out, problems = spec.post_validate(state["inputs"], parsed)
        return {"output": out, "problems": problems, "trace": [*state.get("trace", []), f"{spec.name}:post_validate"]}

    g = StateGraph(AgentState)
    g.add_node("prepare", prepare)
    g.add_node("generate", generate)
    g.add_node("post_validate", post_validate)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "generate")
    g.add_edge("generate", "post_validate")
    g.add_edge("post_validate", END)
    return g.compile(checkpointer=InMemorySaver())


async def run_agent(spec: AgentSpec, gateway: ModelGateway, inputs: dict[str, Any], scope: str) -> AgentRun:
    graph = build_graph(spec, gateway, scope)
    state: AgentState = await graph.ainvoke({"inputs": inputs}, config={"configurable": {"thread_id": scope}})
    return AgentRun(output=state["output"], problems=state.get("problems", []),
                    provenance={**state["provenance"], "agent": spec.name, "prompt_version": spec.prompt_version},
                    trace=state.get("trace", []))

