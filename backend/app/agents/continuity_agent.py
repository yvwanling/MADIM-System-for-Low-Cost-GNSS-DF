from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.tools.navigation_tools import ToolRegistry


class ContinuityAgent(BaseAgent):
    name = "continuity_agent"
    role = "连续性增强 Agent"
    objective = "根据完整性结果执行时序保持、平滑航向序列并检测跳变。"
    allow_llm_planning = False

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    def available_tools(self) -> List[str]:
        return ["apply_temporal_hold", "smooth_heading_series", "detect_heading_jumps"]

    def required_tools(self, board: Dict[str, Any]) -> List[str]:
        return ["apply_temporal_hold", "smooth_heading_series", "detect_heading_jumps"]

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "strategy_report": board.get("strategy_report", {}),
            "integrity_report": board.get("integrity_report", {}),
        }

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "decision_summary": "先利用时序保持稳定弱历元，再平滑航向序列，最后标注航向跳变。",
            "tool_calls": [
                {"tool": "apply_temporal_hold", "arguments": {}},
                {"tool": "smooth_heading_series", "arguments": {}},
                {"tool": "detect_heading_jumps", "arguments": {}},
            ],
            "handoff_to": "explanation_agent",
        }

    def sync_after_tool(self, board: Dict[str, Any], tool_name: str, result: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        if tool_name == "apply_temporal_hold":
            board["continuity_report"] = {**result}
        elif tool_name == "detect_heading_jumps":
            board["continuity_report"] = {
                **board.get("continuity_report", {}),
                **result,
            }

    def validate_run(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        final_epoch_results = board.get("final_epoch_results", [])
        if not final_epoch_results:
            raise RuntimeError(
                "continuity_agent: final_epoch_results 为空。"
                "这通常表示连续性阶段的核心工具链没有完整执行。"
            )

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        board["continuity_report"] = board.get("continuity_report", {
            **results.get("apply_temporal_hold", {}),
            **results.get("detect_heading_jumps", {}),
        })
        return board["continuity_report"]
