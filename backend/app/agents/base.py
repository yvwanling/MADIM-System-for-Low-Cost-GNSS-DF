from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.models.schemas import AgentTrace, ToolCallRecord
from app.services.llm_service import LLMService
from app.tools.navigation_tools import ToolRegistry


@dataclass
class PlanStep:
    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    name = "base_agent"
    role = "generic agent"
    objective = ""
    allow_llm_planning = False

    def __init__(self, registry: ToolRegistry, llm: Optional[LLMService] = None) -> None:
        self.registry = registry
        self.llm = llm or LLMService()

    def available_tools(self) -> List[str]:
        raise NotImplementedError

    def required_tools(self, board: Dict[str, Any]) -> List[str]:
        return []

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def summarize_result(self, tool_name: str, result: Dict[str, Any]) -> str:
        preview = ", ".join([f"{key}={value}" for key, value in list(result.items())[:4]])
        return preview if preview else "工具已执行。"

    def sync_after_tool(
        self,
        board: Dict[str, Any],
        tool_name: str,
        result: Dict[str, Any],
        results: Dict[str, Dict[str, Any]],
    ) -> None:
        return None

    def validate_run(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        return None

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        raise NotImplementedError

    def _llm_plan(self, board: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.allow_llm_planning:
            return None
        if not board["request"].get("use_llm") or not self.llm.is_available():
            return None
        tool_desc = self.registry.describe_tools(self.available_tools())
        required_tools = self.required_tools(board)
        system_prompt = (
            f"你是 {self.role}。你的目标：{self.objective}。\n"
            "你可以在可用工具中生成一个 JSON 执行计划。\n"
            f"必须包含这些核心工具并保持顺序不变：{required_tools if required_tools else '无强制工具'}。\n"
            "输出格式："
            '{"decision_summary":"...","tool_calls":[{"tool":"tool_name","arguments":{...}}],"handoff_to":"next_agent_or_none"}'
            "。禁止输出 JSON 以外的任何文本。"
        )
        user_prompt = str({"tools": tool_desc, "context": self.build_llm_context(board)})
        plan = self.llm.plan_json(system_prompt, user_prompt)
        if not isinstance(plan, dict):
            return None
        return plan

    def _is_plan_safe_and_complete(self, plan: Dict[str, Any], board: Dict[str, Any]) -> bool:
        tool_calls = plan.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            return False
        available = set(self.available_tools())
        selected_tools: List[str] = []
        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                return False
            tool_name = raw_call.get("tool")
            if not isinstance(tool_name, str) or tool_name not in available:
                return False
            selected_tools.append(tool_name)
        required = self.required_tools(board)
        if not required:
            return True
        return selected_tools == required

    def _choose_plan(self, board: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        fallback = self.fallback_plan(board)
        llm_plan = self._llm_plan(board)
        if llm_plan is None:
            return fallback, False
        if not self._is_plan_safe_and_complete(llm_plan, board):
            board.setdefault("warnings", []).append(
                f"{self.name}: LLM 计划未满足必需工具链，已回退到规则计划。"
            )
            return fallback, False
        return llm_plan, True

    def run(self, board: Dict[str, Any]) -> Dict[str, Any]:
        plan, used_llm = self._choose_plan(board)
        decision_summary = str(plan.get("decision_summary", "按照默认策略执行。"))
        handoff_to = plan.get("handoff_to")
        results: Dict[str, Dict[str, Any]] = {}
        tool_calls: List[ToolCallRecord] = []
        for raw_call in plan.get("tool_calls", []):
            tool_name = raw_call["tool"]
            arguments = dict(raw_call.get("arguments", {}))
            result = self.registry.call(tool_name, arguments, board)
            results[tool_name] = result
            self.sync_after_tool(board, tool_name, result, results)
            source = self.registry.source_map().get(tool_name, "local-python")
            tool_calls.append(
                ToolCallRecord(
                    tool=tool_name,
                    arguments=arguments,
                    source=source,
                    result_summary=self.summarize_result(tool_name, result),
                )
            )
        self.validate_run(board, results)
        output = self.finalize(board, results, decision_summary)
        board.setdefault("agent_trace", []).append(
            AgentTrace(
                agent=self.name,
                role=self.role,
                objective=self.objective,
                decision_summary=decision_summary,
                used_llm=used_llm,
                handoff_to=handoff_to,
                tool_calls=tool_calls,
            )
        )
        return output
