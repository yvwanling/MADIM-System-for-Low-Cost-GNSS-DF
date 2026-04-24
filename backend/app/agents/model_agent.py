from typing import Any, Dict

from app.agents.base import BaseAgent


class ModelSelectionAgent(BaseAgent):
    name = "model_selection"

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        quality_score = context["quality"]["quality_score"]
        sats = context["quality"]["sats_metric"]
        if sats >= 12 and quality_score >= 0.60:
            model_choice = "multi_gnss_constraint_mode"
            reason = "可见卫星数量充足，适合采用多系统约束求解。"
        elif sats >= 8 and quality_score >= 0.40:
            model_choice = "single_gnss_fallback_mode"
            reason = "观测质量波动，切换到保守单系统回退模式。"
        else:
            model_choice = "degraded_observation_mode"
            reason = "卫星数量不足或质量较差，进入退化观测模式，仅输出低置信度结果。"
        return {"model_choice": model_choice, "model_reason": reason}
