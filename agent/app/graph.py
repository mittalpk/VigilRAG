"""
VigilRAG Agent Service — LangGraph StateGraph Workflow.
Provides a multi-agent graph: Planner → Executor → Evaluator → Responder.
"""
from __future__ import annotations

import os
import operator
import logging
import time
import asyncio
from typing import TypedDict, Annotated, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from .tools import REGISTERED_TOOLS

logger = logging.getLogger(__name__)

# ── Tunable Timeouts ──────────────────────────────────────────────────────────
LLM_TIMEOUT_S   = int(os.environ.get("LLM_TIMEOUT_S",   "60"))   # per LLM call
TOOL_TIMEOUT_S  = int(os.environ.get("TOOL_TIMEOUT_S",  "30"))   # per tool call


# ── State Schema ──────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    task: str
    messages: Annotated[list[BaseMessage], add_messages]
    plan: list[dict[str, Any]]
    results: Annotated[list[dict[str, Any]], operator.add]
    iteration: int
    max_iterations: int
    sufficient: bool
    missing_information: str
    sub_queries: list[str]
    all_evidence: list[dict[str, Any]]
    final_answer: str


# ── Build Graph ───────────────────────────────────────────────────────────────

def build_graph() -> Any:
    """
    Compile the LangGraph multi-agent graph with US-029 Iterative Reasoning Loop.
    Workflow: Plan -> Execute -> Evaluate -> (Decompose -> Execute -> Evaluate)* -> Respond
    """
    from .config import settings
    google_api_key = settings.gemini_api_key.get_secret_value()
    
    # Fast model for planning, decomposition, and evaluation
    llm_flash = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0,
        google_api_key=google_api_key,
    )
    
    # High-quality model for final synthesis
    llm_pro = ChatGoogleGenerativeAI(
        model="gemini-2.5-pro",
        temperature=0,
        google_api_key=google_api_key,
    )
    
    planner_llm = llm_flash.bind_tools(REGISTERED_TOOLS)

    # ── Node Implementations ──────────────────────────────────────────────────

    async def node_plan(state: AgentState) -> dict:
        start_time = time.time()
        logger.info("Generating initial execution plan (Flash)...")
        system = SystemMessage(content=(
            "You are an expert VigilRAG AI engineer. Break the user's task into a concrete, "
            "ordered plan of tool calls using the tools available to you. "
            "Call all relevant tools needed to answer the user's task."
        ))
        try:
            resp = await asyncio.wait_for(
                planner_llm.ainvoke([system] + state["messages"]),
                timeout=LLM_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            logger.warning(f"Plan LLM call timed out after {LLM_TIMEOUT_S}s — using fallback plan.")
            return {
                "plan": [{"tool": "search_confluence", "input": {"query": state["task"]}}],
                "results": [{"step": "plan", "count": 1, "note": "timeout_fallback"}],
                "iteration": state.get("iteration", 0) + 1,
            }

        plan = []
        if hasattr(resp, "tool_calls") and resp.tool_calls:
            for tc in resp.tool_calls:
                tool_name = tc.get("name", "")
                if tool_name.startswith("default_api:"):
                    tool_name = tool_name.split(":", 1)[1]
                plan.append({"tool": tool_name, "input": tc.get("args", {})})

        if not plan:
            import json, re
            text_content = ""
            if isinstance(resp.content, str):
                text_content = resp.content
            elif isinstance(resp.content, list):
                text_content = "".join([c.get("text", "") for c in resp.content if isinstance(c, dict) and "text" in c])
            match = re.search(r"\[\s*\{.*\}\s*\]", text_content, re.DOTALL)
            raw = match.group(0) if match else re.sub(r"```json|```", "", text_content).strip()
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    plan = parsed
            except Exception as e:
                logger.warning(f"Plan JSON parse failed ({e})")

        if not plan:
            plan = [{"tool": "search_confluence", "input": {"query": state["task"]}}]

        duration = time.time() - start_time
        logger.info(f"Plan generated in {duration:.2f}s: {len(plan)} step(s)")
        return {
            "plan": plan,
            "results": [{"step": "plan", "count": len(plan)}],
            "iteration": state.get("iteration", 0) + 1,
        }

    async def node_execute(state: AgentState) -> dict:
        """Parallel Execution of planned steps with evidence deduplication tracking."""
        start_time = time.time()
        steps = state.get("plan", [])
        if not steps:
            return {}

        logger.info(f"Executing {len(steps)} steps in parallel (iteration {state.get('iteration', 1)})...")

        async def run_step(step):
            tool_name = step.get("tool", "")
            if tool_name.startswith("default_api:"):
                tool_name = tool_name.split(":", 1)[1]

            tool_input = step.get("input", {})
            tool = next((t for t in REGISTERED_TOOLS if t.name == tool_name), None)
            if not tool:
                return {"step": "execute", "tool": tool_name, "error": f"Unknown tool"}

            try:
                output = await asyncio.wait_for(tool.arun(tool_input), timeout=TOOL_TIMEOUT_S)
                return {"step": "execute", "tool": tool_name, "output": str(output)[:500]}
            except asyncio.TimeoutError:
                return {"step": "execute", "tool": tool_name, "error": "timeout"}
            except Exception as e:
                return {"step": "execute", "tool": tool_name, "error": str(e)}

        results = await asyncio.gather(*[run_step(s) for s in steps])
        
        # Deduplicate and accumulate evidence items
        existing_evidence = state.get("all_evidence", [])
        existing_keys = {str(item.get("chunk_id") or item.get("output", "")) for item in existing_evidence}
        
        new_evidence = list(existing_evidence)
        for r in results:
            key = str(r.get("chunk_id") or r.get("output", ""))
            if key and key not in existing_keys:
                new_evidence.append(r)
                existing_keys.add(key)

        duration = time.time() - start_time
        logger.info(f"Execution finished in {duration:.2f}s (Accumulated evidence: {len(new_evidence)})")
        return {
            "results": results,
            "all_evidence": new_evidence,
        }

    async def node_evaluate(state: AgentState) -> dict:
        """US-029: Evaluates if accumulated evidence is sufficient to answer the task."""
        current_iteration = state.get("iteration", 1)
        max_iters = state.get("max_iterations", 3)
        
        if current_iteration >= max_iters:
            logger.info(f"Max iterations reached ({current_iteration}/{max_iters}). Moving to response.")
            return {"sufficient": True, "missing_information": ""}

        # If previous iteration produced no new evidence, terminate early to avoid loops
        results = state.get("results", [])
        latest_results = [r for r in results if r.get("step") == "execute"]
        if current_iteration > 1 and not latest_results:
            logger.info("No new execution results in follow-up iteration. Terminating early.")
            return {"sufficient": True, "missing_information": ""}

        system = SystemMessage(content=(
            "You are a critical quality evaluator for an AI Q&A agent.\n"
            "Assess whether the collected execution evidence is sufficient to completely answer the user's task.\n"
            "Respond in JSON format with two keys:\n"
            '  "sufficient": true/false,\n'
            '  "missing_information": "description of missing details if sufficient is false"\n'
        ))
        
        evidence_summary = "\n".join(
            f"- {r.get('tool')}: {r.get('output', r.get('error', ''))}"
            for r in state.get("results", []) if r.get("step") == "execute"
        )
        prompt = f"Task: {state['task']}\nAccumulated Evidence:\n{evidence_summary}"
        
        try:
            resp = await asyncio.wait_for(llm_flash.ainvoke([system, HumanMessage(content=prompt)]), timeout=LLM_TIMEOUT_S)
            import json, re
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            match = re.search(r"\{.*\}", text, re.DOTALL)
            parsed = json.loads(match.group(0)) if match else {}
            sufficient = bool(parsed.get("sufficient", True))
            missing = str(parsed.get("missing_information", ""))
        except Exception as exc:
            logger.warning(f"Sufficiency evaluation error ({exc}); defaulting to sufficient=True")
            sufficient = True
            missing = ""

        logger.info(f"Sufficiency evaluation (Iteration {current_iteration}): sufficient={sufficient}")
        return {"sufficient": sufficient, "missing_information": missing}

    async def node_decompose(state: AgentState) -> dict:
        """US-029: Decomposes missing information into follow-up tool sub-queries."""
        logger.info("Decomposing missing information into follow-up sub-queries...")
        system = SystemMessage(content=(
            "Generate 1-2 targeted follow-up tool calls to retrieve missing information for the task.\n"
            "Return tool calls using the available tools."
        ))
        prompt = f"Original Task: {state['task']}\nMissing Information: {state.get('missing_information', '')}"
        
        try:
            resp = await asyncio.wait_for(planner_llm.ainvoke([system, HumanMessage(content=prompt)]), timeout=LLM_TIMEOUT_S)
            plan = []
            if hasattr(resp, "tool_calls") and resp.tool_calls:
                for tc in resp.tool_calls:
                    tool_name = tc.get("name", "")
                    if tool_name.startswith("default_api:"):
                        tool_name = tool_name.split(":", 1)[1]
                    plan.append({"tool": tool_name, "input": tc.get("args", {})})
            
            if not plan:
                plan = [{"tool": "search_confluence", "input": {"query": state.get("missing_information", state["task"])}}]
        except Exception as exc:
            logger.warning(f"Decomposition failed ({exc}); using fallback sub-query.")
            plan = [{"tool": "search_confluence", "input": {"query": state["task"]}}]

        return {
            "plan": plan,
            "iteration": state.get("iteration", 1) + 1,
            "sub_queries": [p.get("tool", "") for p in plan],
        }

    def should_continue(state: AgentState) -> str:
        """US-029: Conditional edge evaluating whether to decompose for next iteration or respond."""
        iteration = state.get("iteration", 1)
        max_iters = state.get("max_iterations", 3)
        sufficient = state.get("sufficient", False)

        if sufficient or iteration >= max_iters:
            return "respond"
        return "decompose"

    async def node_respond(state: AgentState) -> dict:
        logger.info("Composing final response (Pro)...")
        summary = "\n".join(
            f"- {r.get('tool')}: {r.get('output', r.get('error', 'ok'))}"
            for r in state.get("results", [])
            if r.get("step") == "execute"
        )
        system = SystemMessage(content=(
            f"You are summarizing the outcome of an AI agent task.\n"
            f"Execution log:\n{summary}\n"
            f"Write a concise professional summary for the user. Focus on facts found."
        ))
        resp = await llm_pro.ainvoke([system] + state["messages"])

        text_content = ""
        if isinstance(resp.content, str):
            text_content = resp.content
        elif isinstance(resp.content, list):
            text_content = "".join([c.get("text", "") for c in resp.content if isinstance(c, dict) and "text" in c])
            if not text_content: text_content = str(resp.content)
            
        return {"final_answer": text_content}

    # ── Wire Graph ────────────────────────────────────────────────────────────
    workflow = StateGraph(AgentState)

    workflow.add_node("plan", node_plan)
    workflow.add_node("execute", node_execute)
    workflow.add_node("evaluate", node_evaluate)
    workflow.add_node("decompose", node_decompose)
    workflow.add_node("respond", node_respond)

    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "execute")
    workflow.add_edge("execute", "evaluate")
    workflow.add_conditional_edges("evaluate", should_continue, {"decompose": "decompose", "respond": "respond"})
    workflow.add_edge("decompose", "execute")
    workflow.add_edge("respond", END)

    return workflow.compile()


# ── Lazy singleton (allows /health without GOOGLE_API_KEY; LLM routes fail until configured) ──
_graph = None


def get_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def __getattr__(name: str) -> Any:
    if name == "graph":
        return get_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
