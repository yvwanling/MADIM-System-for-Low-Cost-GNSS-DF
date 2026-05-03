from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.services.llm_service import LLMService
from app.tools.navigation_tools import ToolRegistry


class ScenarioPlanningAgent(BaseAgent):
    name = "scenario_planner_agent"
    role = "场景策略规划 Agent"
    objective = "根据用户目标、历史风险轨迹和 GNSS 场景技能包，规划分析/解算策略，并给出下一次采集建议。"
    allow_llm_planning = False

    def __init__(self, registry: ToolRegistry, llm: LLMService | None = None) -> None:
        super().__init__(registry, llm=llm)

    def available_tools(self) -> List[str]:
        return ["load_navigation_skills", "plan_analysis_strategy", "recommend_collection_actions"]

    def required_tools(self, board: Dict[str, Any]) -> List[str]:
        return ["load_navigation_skills", "plan_analysis_strategy", "recommend_collection_actions"]

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "decision_summary": "先按目标加载 GNSS 场景技能包，再规划解算策略，最后结合历史风险热点给出下一次采集建议。",
            "tool_calls": [
                {"tool": "load_navigation_skills", "arguments": {}},
                {"tool": "plan_analysis_strategy", "arguments": {}},
                {"tool": "recommend_collection_actions", "arguments": {}},
            ],
            "handoff_to": "done",
        }

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "goal": board.get("scenario_goal"),
            "summary_payload": board.get("summary_payload", {}),
            "trajectory": board.get("optional_context", {}).get("trajectory", {}),
            "quality_report": board.get("quality_report", {}),
        }

    def sync_after_tool(self, board: Dict[str, Any], tool_name: str, result: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> None:
        if tool_name == "load_navigation_skills":
            board["scenario_skill_context"] = result
        elif tool_name == "plan_analysis_strategy":
            board["scenario_strategy_plan"] = result
        elif tool_name == "recommend_collection_actions":
            board.setdefault("scenario_strategy_plan", {})["collection_advice"] = result.get("collection_advice", [])

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        plan = dict(board.get("scenario_strategy_plan", {}))
        plan["selected_skills"] = board.get("scenario_skill_context", {}).get("skill_names", [])
        if "collection_advice" not in plan:
            plan["collection_advice"] = results.get("recommend_collection_actions", {}).get("collection_advice", [])

        rationale = "；".join(plan.get("rationale_points", []))
        if board.get("request", {}).get("use_llm") and self.llm.is_available():
            system_prompt = (
                "你是 GNSS 场景策略规划 Agent。请根据用户目标、技能包、历史风险热点，"
                "用专业中文概括推荐策略，不要改动结构化参数，只丰富原因说明。"
            )
            user_prompt = str(
                {
                    "goal": board.get("scenario_goal"),
                    "plan": plan,
                    "skills": board.get("scenario_skill_context", {}),
                    "trajectory": board.get("optional_context", {}).get("trajectory", {}),
                }
            )
            try:
                text = self.llm.summarize(system_prompt, user_prompt)
                if text:
                    rationale = text
            except Exception:
                pass
        plan["rationale"] = rationale or "系统基于目标偏好、风险热点和 GNSS 场景技能包给出上述建议。"
        board["scenario_strategy_plan"] = plan
        return plan
