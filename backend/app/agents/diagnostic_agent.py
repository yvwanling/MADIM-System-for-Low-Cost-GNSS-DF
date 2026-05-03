from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.services.llm_service import LLMService
from app.tools.navigation_tools import ToolRegistry


class HotspotDiagnosticAgent(BaseAgent):
    name = "hotspot_diagnostic_agent"
    role = "异常窗口深挖诊断 Agent"
    objective = "围绕用户选中的风险热点窗口，结合历元质量、置信度、跳变、候选分离度和基线约束，生成局部根因诊断与处理建议。"
    allow_llm_planning = False

    def __init__(self, registry: ToolRegistry, llm: LLMService | None = None) -> None:
        super().__init__(registry, llm=llm)

    def available_tools(self) -> List[str]:
        return ["diagnose_hotspot_window"]

    def required_tools(self, board: Dict[str, Any]) -> List[str]:
        return ["diagnose_hotspot_window"]

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "decision_summary": "读取选中风险热点的局部窗口，提取质量、置信度、卫星数、分离度、阈值误差与跳变证据，形成可执行诊断建议。",
            "tool_calls": [{"tool": "diagnose_hotspot_window", "arguments": {}}],
            "handoff_to": "explanation_agent",
        }

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "hotspot_id": board.get("diagnosis_request", {}).get("hotspot_id"),
            "summary_payload": board.get("summary_payload", {}),
            "trajectory_stats": board.get("optional_context", {}).get("trajectory", {}).get("stats", {}),
        }

    def sync_after_tool(self, board: Dict[str, Any], tool_name: str, result: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        if tool_name == "diagnose_hotspot_window":
            board["hotspot_diagnosis"] = result

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        result = dict(results.get("diagnose_hotspot_window", {}))
        if board.get("diagnosis_request", {}).get("use_llm") and self.llm.is_available():
            try:
                system_prompt = (
                    "你是 GNSS 风险热点诊断专家。请基于结构化证据，用中文生成简洁但专业的局部异常诊断。"
                    "不要编造数值，不要改变建议策略参数。"
                )
                text = self.llm.summarize(system_prompt, str(result))
                if text:
                    result["diagnosis"] = text
            except Exception:
                pass
        board["hotspot_diagnosis"] = result
        return result
