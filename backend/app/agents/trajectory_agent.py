
from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.tools.navigation_tools import ToolRegistry


class TrajectoryVisualizationAgent(BaseAgent):
    name = "trajectory_agent"
    role = "轨迹展示 Agent"
    objective = "从历元级导航结果中提取可视化轨迹、风险分段、回放帧和策略叠加信息，供前端地图展示。"
    allow_llm_planning = False

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    def available_tools(self) -> List[str]:
        return ["build_trajectory_payload"]

    def required_tools(self, board: Dict[str, Any]) -> List[str]:
        return ["build_trajectory_payload"]

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "decision_summary": "提取轨迹点、回放帧、风险分段和策略叠加信息，供前端高德地图展示与回放。",
            "tool_calls": [
                {"tool": "build_trajectory_payload", "arguments": {}}
            ],
            "handoff_to": "explanation_agent",
        }

    def sync_after_tool(self, board: Dict[str, Any], tool_name: str, result: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        if tool_name == "build_trajectory_payload":
            board.setdefault("optional_context", {})["trajectory"] = result

    def validate_run(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        trajectory = board.get("optional_context", {}).get("trajectory", {})
        if not trajectory.get("points"):
            raise RuntimeError("trajectory_agent: 轨迹点为空，无法进行地图展示。")

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        payload = results.get("build_trajectory_payload", {})
        board.setdefault("optional_context", {})["trajectory"] = payload
        return payload
