from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.tools.navigation_tools import ToolRegistry


class StrategyAgent(BaseAgent):
    name = "strategy_agent"
    role = "解算策略 Agent"
    objective = "根据当前质量状态与重试轮数，选择导航模式、候选解预算和回退策略。"
    allow_llm_planning = False

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    def available_tools(self) -> List[str]:
        return ["choose_navigation_mode", "configure_candidate_budget", "configure_retry_policy"]

    def required_tools(self, board: Dict[str, Any]) -> List[str]:
        return ["choose_navigation_mode", "configure_candidate_budget", "configure_retry_policy"]

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "quality_report": board.get("quality_report", {}),
            "retry_round": board.get("retry_round", 0),
            "request": board.get("request", {}),
        }

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "decision_summary": "结合观测质量与用户设置，先选择导航模式，再配置候选解预算和重试门限。",
            "tool_calls": [
                {"tool": "choose_navigation_mode", "arguments": {}},
                {"tool": "configure_candidate_budget", "arguments": {}},
                {"tool": "configure_retry_policy", "arguments": {}},
            ],
            "handoff_to": "ambiguity_resolution_agent",
        }

    def sync_after_tool(self, board: Dict[str, Any], tool_name: str, result: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        if tool_name == "choose_navigation_mode":
            board["strategy_report"] = {**result}
        elif tool_name == "configure_candidate_budget":
            board["strategy_report"] = {
                **board.get("strategy_report", {}),
                **result,
            }
        elif tool_name == "configure_retry_policy":
            board["strategy_retry_policy"] = result

    def validate_run(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        strategy = board.get("strategy_report", {})
        if not strategy.get("strategy_profile"):
            raise RuntimeError("strategy_agent: strategy_profile 未生成。")
        if "candidate_count" not in strategy:
            raise RuntimeError("strategy_agent: candidate_count 未生成，预算配置失败。")
        if not board.get("strategy_retry_policy"):
            raise RuntimeError("strategy_agent: strategy_retry_policy 未生成。")

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        board["strategy_report"] = board.get("strategy_report", {
            **results.get("choose_navigation_mode", {}),
            **results.get("configure_candidate_budget", {}),
        })
        board.setdefault("strategy_history", []).append(board["strategy_report"]["strategy_profile"])
        board["strategy_retry_policy"] = board.get("strategy_retry_policy", results.get("configure_retry_policy", {}))
        return board["strategy_report"]
