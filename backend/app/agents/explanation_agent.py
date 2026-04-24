from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.services.llm_service import LLMService
from app.tools.navigation_tools import ToolRegistry


class ExplanationAgent(BaseAgent):
    name = "explanation_agent"
    role = "解释与报告 Agent"
    objective = "汇总多智能体分析结果，形成可读报告；若启用大模型，则生成更自然的导航诊断解释。"

    def __init__(self, registry: ToolRegistry, llm: LLMService | None = None) -> None:
        super().__init__(registry, llm=llm)

    def available_tools(self) -> List[str]:
        return ["compile_report_payload", "reverse_geocode_midpoint"]

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "summary_payload": board.get("summary_payload", {}),
            "optional_context": board.get("optional_context", {}),
        }

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        tool_calls = [{"tool": "compile_report_payload", "arguments": {}}]
        if board["request"].get("enable_amap_geocode"):
            tool_calls.append({"tool": "reverse_geocode_midpoint", "arguments": {}})
        return {
            "decision_summary": "整理报告输入，如果用户启用了地理语义增强则尝试调用高德逆地理编码。",
            "tool_calls": tool_calls,
            "handoff_to": "done",
        }

    def _fallback_explanation(self, board: Dict[str, Any]) -> str:
        summary = board.get("summary_payload", {})
        optional = board.get("optional_context", {})
        place = optional.get("amap_regeocode", {}).get("formatted_address")
        place_text = f" 数据集中心位置约为 {place}。" if place else ""
        return (
            f"本次导航 Agent 共完成 {summary.get('total_epochs', 0)} 个历元分析，"
            f"固定成功率 {summary.get('fix_rate', 0.0):.2%}，"
            f"平均置信度 {summary.get('avg_confidence', 0.0):.2f}。"
            f"主导策略为 {summary.get('dominant_strategy', 'unknown')}，"
            f"共重试 {summary.get('retry_rounds', 0)} 轮。"
            "系统由 Supervisor 统筹，依次调用数据接入、质量控制、策略规划、模糊度搜索、完好性监测、连续性增强和解释报告等 Agent。"
            f"{place_text}"
        )

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        payload = results.get("compile_report_payload", {})
        board["report_payload"] = payload
        if results.get("reverse_geocode_midpoint"):
            board.setdefault("optional_context", {})["amap_regeocode"] = results["reverse_geocode_midpoint"]
        explanation = self._fallback_explanation(board)
        if board["request"].get("use_llm") and self.llm.is_available():
            system_prompt = (
                "你是导航解释 Agent。请根据结构化分析结果输出 1 段专业中文解释，"
                "说明系统如何通过多智能体协作完成导航分析，并点出主要风险与优势。"
                "不要编造数据。"
            )
            user_prompt = str({
                "summary_payload": payload,
                "optional_context": board.get("optional_context", {}),
                "quality_report": board.get("quality_report", {}),
                "strategy_report": board.get("strategy_report", {}),
                "integrity_report": board.get("integrity_report", {}),
            })
            try:
                llm_text = self.llm.summarize(system_prompt, user_prompt)
                if llm_text:
                    explanation = llm_text
            except Exception:
                pass
        board["final_explanation"] = explanation
        return {"explanation": explanation}

    def answer_followup(self, board: Dict[str, Any], question: str, use_llm: bool = True) -> str:
        if use_llm and self.llm.is_available():
            system_prompt = (
                "你是导航系统解释 Agent。你只能根据已有分析结果回答用户问题，"
                "不允许虚构不存在的实验结论。回答要简洁、专业、清楚。"
            )
            user_prompt = str(
                {
                    "question": question,
                    "summary": board.get("summary_payload", {}),
                    "quality_report": board.get("quality_report", {}),
                    "strategy_report": board.get("strategy_report", {}),
                    "integrity_report": board.get("integrity_report", {}),
                    "continuity_report": board.get("continuity_report", {}),
                    "optional_context": board.get("optional_context", {}),
                }
            )
            try:
                text = self.llm.summarize(system_prompt, user_prompt)
                if text:
                    return text
            except Exception:
                pass
        return (
            f"根据最近一次分析，本次数据的固定成功率为 {board.get('summary_payload', {}).get('fix_rate', 0.0):.2%}，"
            f"平均置信度为 {board.get('summary_payload', {}).get('avg_confidence', 0.0):.2f}。"
            f"你提到的问题是“{question}”。当前可直接参考的主要模块包括质量控制、策略规划、完好性监测和连续性增强。"
        )
