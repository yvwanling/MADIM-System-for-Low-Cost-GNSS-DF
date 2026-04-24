from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.tools.navigation_tools import ToolRegistry


class SupervisorAgent(BaseAgent):
    name = "supervisor_agent"
    role = "导航任务总控 Agent"
    objective = "决定当前阶段应该调用哪个专业智能体，以及是否需要基于完整性结果发起重试。"

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    def available_tools(self) -> List[str]:
        return ["configure_retry_policy"]

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "phase": board.get("supervisor_phase", "start"),
            "quality_report": board.get("quality_report", {}),
            "strategy_report": board.get("strategy_report", {}),
            "integrity_report": board.get("integrity_report", {}),
            "retry_round": board.get("retry_round", 0),
        }

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        phase = board.get("supervisor_phase", "start")
        if phase == "post_strategy":
            return {
                "decision_summary": "完成策略设定后，进入候选解搜索与完整性判断阶段。",
                "tool_calls": [],
                "handoff_to": "ambiguity_resolution_agent",
            }
        if phase == "post_integrity":
            need_retry = board.get("retry_decision", {}).get("need_retry", False)
            if need_retry:
                return {
                    "decision_summary": "完整性结果未达标，回退到策略 Agent 并提高候选搜索预算。",
                    "tool_calls": [],
                    "handoff_to": "strategy_agent",
                }
            return {
                "decision_summary": "完整性结果满足要求，进入连续性增强与报告生成阶段。",
                "tool_calls": [],
                "handoff_to": "continuity_agent",
            }
        return {
            "decision_summary": "开始执行导航多智能体工作流：接入数据、质量控制、策略规划、候选解搜索、完整性监测、连续性增强与解释。",
            "tool_calls": [],
            "handoff_to": "ingestion_agent",
        }

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        return {"status": "routed", "decision_summary": decision_summary}
