from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.tools.navigation_tools import ToolRegistry


class QualityControlAgent(BaseAgent):
    name = "quality_control_agent"
    role = "观测质量控制 Agent"
    objective = "评估历元质量、识别异常观测，并给出数据是否适合进入高可信导航分析的判断。"
    allow_llm_planning = False

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    def available_tools(self) -> List[str]:
        return ["compute_quality_metrics", "detect_outlier_epochs", "classify_quality_state"]

    def required_tools(self, board: Dict[str, Any]) -> List[str]:
        return ["compute_quality_metrics", "detect_outlier_epochs", "classify_quality_state"]

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {"ingestion_report": board.get("ingestion_report", {})}

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "decision_summary": "先计算全局与历元级质量指标，再识别异常历元，最后给出质量等级与主导问题。",
            "tool_calls": [
                {"tool": "compute_quality_metrics", "arguments": {}},
                {"tool": "detect_outlier_epochs", "arguments": {}},
                {"tool": "classify_quality_state", "arguments": {}},
            ],
            "handoff_to": "strategy_agent",
        }

    def sync_after_tool(self, board: Dict[str, Any], tool_name: str, result: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        if tool_name == "compute_quality_metrics":
            board["quality_metrics"] = result
        elif tool_name == "detect_outlier_epochs":
            board["quality_outliers"] = result
        elif tool_name == "classify_quality_state":
            board["quality_report"] = {
                **board.get("quality_metrics", {}),
                **result,
                "outlier_count": board.get("quality_outliers", {}).get("outlier_count", 0),
                "outlier_ratio": board.get("quality_outliers", {}).get("outlier_ratio", 0.0),
            }

    def validate_run(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        if not board.get("quality_metrics"):
            raise RuntimeError("quality_control_agent: 缺少 quality_metrics，中间状态未正确写回。")
        if not board.get("quality_outliers"):
            raise RuntimeError("quality_control_agent: 缺少 quality_outliers，中间状态未正确写回。")
        if not board.get("quality_report"):
            raise RuntimeError("quality_control_agent: 缺少 quality_report，质量分级未完成。")

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        board["quality_report"] = board.get("quality_report", {
            **results.get("compute_quality_metrics", {}),
            **results.get("classify_quality_state", {}),
            "outlier_count": results.get("detect_outlier_epochs", {}).get("outlier_count", 0),
            "outlier_ratio": results.get("detect_outlier_epochs", {}).get("outlier_ratio", 0.0),
        })
        return board["quality_report"]
