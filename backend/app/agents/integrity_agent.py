from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.tools.navigation_tools import ToolRegistry


class IntegrityMonitoringAgent(BaseAgent):
    name = "integrity_agent"
    role = "完好性监测 Agent"
    objective = "利用基线约束、动态阈值和候选分离度判断结果是否可信，并决定是否需要重试。"
    allow_llm_planning = False

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    def available_tools(self) -> List[str]:
        return ["apply_dynamic_baseline_constraint", "estimate_confidence", "assess_retry_need"]

    def required_tools(self, board: Dict[str, Any]) -> List[str]:
        return ["apply_dynamic_baseline_constraint", "estimate_confidence", "assess_retry_need"]

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "strategy_report": board.get("strategy_report", {}),
            "ambiguity_report": board.get("ambiguity_report", {}),
            "retry_round": board.get("retry_round", 0),
        }

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "decision_summary": "先用动态阈值执行基线约束筛选，再估计历元置信度与风险，最后判断是否需要重试。",
            "tool_calls": [
                {"tool": "apply_dynamic_baseline_constraint", "arguments": {}},
                {"tool": "estimate_confidence", "arguments": {}},
                {"tool": "assess_retry_need", "arguments": {}},
            ],
            "handoff_to": "supervisor_agent",
        }

    def sync_after_tool(self, board: Dict[str, Any], tool_name: str, result: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        if tool_name == "apply_dynamic_baseline_constraint":
            board["integrity_constraint_report"] = result
        elif tool_name == "estimate_confidence":
            board["integrity_report"] = {
                **result,
                **board.get("integrity_constraint_report", {}),
            }
        elif tool_name == "assess_retry_need":
            board["retry_decision"] = result

    def validate_run(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        integrity = board.get("integrity_report", {})
        if "fix_rate" not in integrity:
            raise RuntimeError("integrity_agent: fix_rate 未生成。")
        if not board.get("retry_decision"):
            raise RuntimeError("integrity_agent: retry_decision 未生成。")

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        board["integrity_report"] = board.get("integrity_report", {
            **results.get("estimate_confidence", {}),
            **results.get("apply_dynamic_baseline_constraint", {}),
        })
        board["retry_decision"] = board.get("retry_decision", results.get("assess_retry_need", {}))
        return board["integrity_report"]
