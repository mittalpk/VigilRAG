"""
Unit tests for US-029 Iterative Reasoning Loop in LangGraph agent graph.
"""

import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

os.environ["INTERNAL_API_KEY"] = "secure-test-internal-api-key-9999"
os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
os.environ["GOOGLE_API_KEY"] = "fake-gemini-key"

from agent.app.graph import build_graph, AgentState

@pytest.mark.asyncio
async def test_iterative_loop_max_iterations_enforced():
    """Verify that graph terminates when max_iterations is reached even if evidence is insufficient."""
    graph = build_graph()
    
    # Mock LLM calls: sufficiency evaluation returns False every time
    mock_eval_resp = MagicMock()
    mock_eval_resp.content = '{"sufficient": false, "missing_information": "need more details"}'

    mock_plan_resp = MagicMock()
    mock_plan_resp.tool_calls = [{"name": "search_confluence", "args": {"query": "test query"}}]

    mock_pro_resp = MagicMock()
    mock_pro_resp.content = "Final response summary."

    with patch("langchain_google_genai.ChatGoogleGenerativeAI.ainvoke", new_callable=AsyncMock) as mock_invoke, \
         patch("agent.app.tools.REGISTERED_TOOLS", []):
        mock_invoke.side_effect = [
            mock_plan_resp, # plan (iteration 1)
            mock_eval_resp, # evaluate (iteration 1 -> sufficient=False)
            mock_plan_resp, # decompose (iteration 1 -> produces sub-query plan for iteration 2)
            mock_eval_resp, # evaluate (iteration 2 -> max_iterations=2 reached)
            mock_pro_resp,  # respond
        ]

        state = {
            "task": "Test multi-hop question",
            "messages": [],
            "plan": [],
            "results": [],
            "iteration": 0,
            "max_iterations": 2,
            "sufficient": False,
            "missing_information": "",
            "sub_queries": [],
            "all_evidence": [],
            "final_answer": "",
        }

        res = await graph.ainvoke(state)
        assert res["final_answer"] == "Final response summary."
        assert res["iteration"] <= 2


@pytest.mark.asyncio
async def test_single_pass_max_iterations_one():
    """Verify that max_iterations=1 behaves as single-pass without iteration."""
    graph = build_graph()

    mock_plan_resp = MagicMock()
    mock_plan_resp.tool_calls = [{"name": "search_confluence", "args": {"query": "single pass query"}}]

    mock_pro_resp = MagicMock()
    mock_pro_resp.content = "Single pass answer."

    with patch("langchain_google_genai.ChatGoogleGenerativeAI.ainvoke") as mock_invoke:
        mock_invoke.side_effect = [
            mock_plan_resp, # plan
            mock_pro_resp,  # respond
        ]

        state = {
            "task": "Single pass task",
            "messages": [],
            "plan": [],
            "results": [],
            "iteration": 0,
            "max_iterations": 1,
            "sufficient": False,
            "missing_information": "",
            "sub_queries": [],
            "all_evidence": [],
            "final_answer": "",
        }

        res = await graph.ainvoke(state)
        assert res["final_answer"] == "Single pass answer."
