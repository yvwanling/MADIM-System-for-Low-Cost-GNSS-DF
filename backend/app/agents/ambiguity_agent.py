from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.tools.navigation_tools import ToolRegistry


class AmbiguityResolutionAgent(BaseAgent):
    name = "ambiguity_resolution_agent"
    role = "模糊度搜索 Agent"
    objective = "根据策略生成候选模糊度解，并在低质量场景下触发三步搜索扩展。"

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    def available_tools(self) -> List[str]:
        return ["generate_lambda_candidates", "score_candidate_separation", "expand_three_step_candidates"]

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "strategy_report": board.get("strategy_report", {}),
            "quality_report": board.get("quality_report", {}),
            "retry_round": board.get("retry_round", 0),
        }

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        tool_calls = [{"tool": "generate_lambda_candidates", "arguments": {}}]
        if board.get("strategy_report", {}).get("enable_three_step"):
            tool_calls.append({"tool": "expand_three_step_candidates", "arguments": {}})
        tool_calls.append({"tool": "score_candidate_separation", "arguments": {}})
        return {
            "decision_summary": "先生成每个历元的候选解集合；若策略要求三步搜索，则扩展候选；最后评估分离度。",
            "tool_calls": tool_calls,
            "handoff_to": "integrity_agent",
        }

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        board["ambiguity_report"] = {
            **results.get("generate_lambda_candidates", {}),
            **results.get("score_candidate_separation", {}),
            "three_step_expanded": results.get("expand_three_step_candidates", {}).get("expanded", False),
        }
        return board["ambiguity_report"]
