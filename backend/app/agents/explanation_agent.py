from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

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

    def _compact_followup_context(self, board: Dict[str, Any], question: str) -> Dict[str, Any]:
        """Build a compact, factual context for follow-up Q&A.

        The follow-up answer must be grounded in the latest blackboard.  We keep
        only the decision-relevant fields so the model can reason over retry,
        strategy, hotspot and workflow evidence instead of receiving a large raw
        epoch table.
        """
        optional = board.get("optional_context", {}) or {}
        trajectory = optional.get("trajectory", {}) or {}
        hotspots = trajectory.get("hotspots", []) or []
        hotspot_brief = []
        for h in hotspots[:8]:
            hotspot_brief.append(
                {
                    "id": h.get("id"),
                    "risk_level": h.get("risk_level"),
                    "start_time": h.get("start_time"),
                    "end_time": h.get("end_time"),
                    "avg_confidence": h.get("avg_confidence"),
                    "jump_count": h.get("jump_count"),
                    "reason": h.get("reason"),
                    "recommendation": h.get("recommendation"),
                }
            )
        return {
            "user_question": question,
            "summary": board.get("summary_payload", {}) or {},
            "quality_report": board.get("quality_report", {}) or {},
            "strategy_report": board.get("strategy_report", {}) or {},
            "retry_policy": board.get("strategy_retry_policy", {}) or {},
            "integrity_report": board.get("integrity_report", {}) or {},
            "retry_decision": board.get("retry_decision", {}) or {},
            "continuity_report": board.get("continuity_report", {}) or {},
            "workflow": board.get("workflow", []) or [],
            "protocol_log": board.get("protocol_log", []) or [],
            "warnings": board.get("warnings", []) or [],
            "hotspots": hotspot_brief,
            "collection_advice": trajectory.get("collection_advice", []) or [],
        }

    @staticmethod
    def _fmt_percent(value: Any) -> str:
        try:
            return f"{float(value):.2%}"
        except Exception:
            return "未知"

    @staticmethod
    def _fmt_float(value: Any, digits: int = 3) -> str:
        try:
            return f"{float(value):.{digits}f}"
        except Exception:
            return "未知"

    def _fallback_retry_answer(self, board: Dict[str, Any], question: str) -> str:
        summary = board.get("summary_payload", {}) or {}
        retry_decision = board.get("retry_decision", {}) or {}
        retry_policy = board.get("strategy_retry_policy", {}) or {}
        integrity = board.get("integrity_report", {}) or {}
        protocol_log = board.get("protocol_log", []) or []
        warnings = board.get("warnings", []) or []
        retry_rounds = int(summary.get("retry_rounds", board.get("retry_round", 0)) or 0)
        need_retry = bool(retry_decision.get("need_retry", False))
        fix_rate = float(integrity.get("fix_rate", summary.get("fix_rate", 0.0)) or 0.0)
        high_ratio = float(integrity.get("high_risk_ratio", 0.0) or 0.0)
        min_fix = float(retry_policy.get("min_fix_rate", 0.0) or 0.0)
        max_high = float(retry_policy.get("max_high_risk_ratio", 1.0) or 1.0)
        approved_retry = [e for e in protocol_log if e.get("protocol") == "retry_review" and e.get("status") == "approved"]

        if retry_rounds <= 0 and not approved_retry and not warnings:
            return (
                "根据最近一次分析结果，这次并没有真正触发重试。"
                f"完整性检查中的固定成功率为 {self._fmt_percent(fix_rate)}，"
                f"高风险比例约为 {self._fmt_percent(high_ratio)}；当前重试阈值要求固定率不低于 {self._fmt_percent(min_fix)}、"
                f"高风险比例不高于 {self._fmt_percent(max_high)}。"
                "因此系统判断为“当前完整性满足要求，无需重试”。"
                "如果页面上看到“重试”相关字样，它更多是在说明系统具备重试协议或策略回退机制，而不是本次样例实际执行了重试。"
            )

        reasons = warnings or [retry_decision.get("reason") or "固定率或高风险比例未达标，系统进入重试/恢复判断。"]
        return (
            f"这次触发或经历了 {retry_rounds} 轮重试，主要原因是：{'；'.join(str(x) for x in reasons if x)}。"
            f"触发判断来自 Integrity Agent：固定成功率 {self._fmt_percent(fix_rate)}，高风险比例 {self._fmt_percent(high_ratio)}，"
            f"对比策略阈值为固定率 ≥ {self._fmt_percent(min_fix)}、高风险比例 ≤ {self._fmt_percent(max_high)}。"
            "当指标未满足阈值时，Supervisor 会批准 retry_review 协议，并回到 Strategy Agent 扩大候选预算或切换 recovery 模式。"
        )

    def _fallback_strategy_answer(self, board: Dict[str, Any], question: str) -> str:
        summary = board.get("summary_payload", {}) or {}
        quality = board.get("quality_report", {}) or {}
        strategy = board.get("strategy_report", {}) or {}
        retry_policy = board.get("strategy_retry_policy", {}) or {}
        return (
            "当前策略选择主要由 Strategy Agent 根据质量评估结果、用户候选数量配置和重试轮次共同确定。"
            f"本次平均质量分数为 {self._fmt_float(quality.get('mean_quality_score'))}，"
            f"主导问题为 {', '.join(quality.get('dominant_issues', []) or ['无明显主导异常'])}。"
            f"因此系统选择 {strategy.get('model_choice', 'unknown')} 模式，"
            f"候选解数量为 {strategy.get('candidate_count', '未知')}，搜索半径为 {strategy.get('search_radius_deg', '未知')}°，"
            f"temporal hold 强度为 {strategy.get('hold_strength', '未知')}，策略标签为 {strategy.get('strategy_profile', summary.get('dominant_strategy', 'unknown'))}。"
            f"重试策略阈值为固定率 ≥ {self._fmt_percent(retry_policy.get('min_fix_rate'))}，"
            f"高风险比例 ≤ {self._fmt_percent(retry_policy.get('max_high_risk_ratio'))}。"
        )

    def _fallback_hotspot_answer(self, board: Dict[str, Any], question: str) -> str:
        summary = board.get("summary_payload", {}) or {}
        optional = board.get("optional_context", {}) or {}
        trajectory = optional.get("trajectory", {}) or {}
        hotspots = trajectory.get("hotspots", []) or []
        if not hotspots:
            return (
                "最近一次分析没有形成明显风险热点。"
                f"整体固定成功率为 {self._fmt_percent(summary.get('fix_rate'))}，"
                f"平均置信度为 {self._fmt_float(summary.get('avg_confidence'))}。"
            )
        first = hotspots[0]
        return (
            f"本次共识别到 {len(hotspots)} 个风险热点。最显著的热点是 {first.get('id', 'hotspot-1')}，"
            f"时间范围为 {first.get('start_time', '未知')} 至 {first.get('end_time', '未知')}，"
            f"风险等级为 {first.get('risk_level', '未知')}，平均置信度为 {self._fmt_float(first.get('avg_confidence'))}。"
            f"主要原因是 {first.get('reason', '局部质量下降或连续性风险增加')}。"
            f"建议：{first.get('recommendation', '关注该区段，必要时补采或启用更稳健策略')}。"
        )

    def _fallback_explain_answer(self, board: Dict[str, Any], question: str) -> str:
        summary = board.get("summary_payload", {}) or {}
        quality = board.get("quality_report", {}) or {}
        strategy = board.get("strategy_report", {}) or {}
        integrity = board.get("integrity_report", {}) or {}
        retry_decision = board.get("retry_decision", {}) or {}
        continuity = board.get("continuity_report", {}) or {}
        return (
            f"根据最近一次分析，系统处理了 {summary.get('total_epochs', 0)} 个历元，"
            f"固定成功率为 {self._fmt_percent(summary.get('fix_rate'))}，平均置信度为 {self._fmt_float(summary.get('avg_confidence'))}。"
            f"质量控制阶段给出的平均质量分数为 {self._fmt_float(quality.get('mean_quality_score'))}；"
            f"策略规划阶段选择 {strategy.get('strategy_profile', summary.get('dominant_strategy', 'unknown'))}；"
            f"完整性监测阶段固定率为 {self._fmt_percent(integrity.get('fix_rate', summary.get('fix_rate')))}，"
            f"高风险比例为 {self._fmt_percent(integrity.get('high_risk_ratio', 0.0))}，结论是 {retry_decision.get('reason', '未记录重试判断')}。"
            f"连续性增强阶段检测到 {continuity.get('jump_count', 0)} 次航向跳变。"
            "如果你想追问某个具体环节，可以继续问“策略依据”“风险热点原因”或“是否需要补采”。"
        )

    def _fallback_followup_answer(self, board: Dict[str, Any], question: str) -> str:
        q = (question or "").lower()
        if any(key in q for key in ["重试", "retry", "恢复", "recovery"]):
            return self._fallback_retry_answer(board, question)
        if any(key in q for key in ["策略", "模式", "候选", "搜索半径", "hold", "选择依据"]):
            return self._fallback_strategy_answer(board, question)
        if any(key in q for key in ["热点", "风险", "异常", "跳变", "补采", "采集"]):
            return self._fallback_hotspot_answer(board, question)
        return self._fallback_explain_answer(board, question)

    def answer_followup(self, board: Dict[str, Any], question: str, use_llm: bool = True) -> str:
        context = self._compact_followup_context(board, question)
        if use_llm and self.llm.is_available():
            system_prompt = (
                "你是 GNSS 导航分析系统的解释 Agent。请严格基于用户最近一次分析黑板回答，"
                "不能编造没有出现的数据或结论。回答必须先直接回应问题，再给出证据。"
                "如果用户问题的前提与事实不一致，例如问‘为什么触发重试’但 retry_rounds=0，"
                "必须明确纠正：本次没有触发重试，然后解释系统的重试判断依据。"
                "请使用中文，结构清晰，尽量引用固定成功率、平均置信度、策略参数、风险热点、协议日志等证据。"
            )
            user_prompt = json.dumps(context, ensure_ascii=False, indent=2, default=str)
            try:
                text = self.llm.summarize(system_prompt, user_prompt)
                if text and len(text.strip()) >= 20:
                    return text.strip()
            except Exception as exc:
                board.setdefault("warnings", []).append(f"explanation_agent: LLM 追问回答失败，已使用本地证据回答：{exc}")
        return self._fallback_followup_answer(board, question)
