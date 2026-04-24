from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.ambiguity_agent import AmbiguityResolutionAgent
from app.agents.continuity_agent import ContinuityAgent
from app.agents.explanation_agent import ExplanationAgent
from app.agents.ingestion_agent import IngestionAgent
from app.agents.integrity_agent import IntegrityMonitoringAgent
from app.agents.quality_agent import QualityControlAgent
from app.agents.strategy_agent import StrategyAgent
from app.agents.trajectory_agent import TrajectoryVisualizationAgent
from app.agents.supervisor_agent import SupervisorAgent
from app.core.config import RAW_DATA_DIR
from app.models.schemas import AnalysisResponse, AnalysisSummary, DatasetInfo, EpochResult, FollowupResponse
from app.services.llm_service import LLMService
from app.tools.navigation_tools import ToolRegistry


DATASET_REGISTRY = {
    "google_mtv_local1": {
        "file_path": RAW_DATA_DIR / "MTV.Local1.ublox-F9K.20200206-181434.nmea",
        "reference_path": RAW_DATA_DIR / "MTV.Local1.SPAN.20200206-181434.gga",
        "description": "Google gps-measurement-tools NMEA 示例日志，可用于路线与质量代理测试。",
    },
    "gpskit_test": {
        "file_path": RAW_DATA_DIR / "gpskit_test.nmea",
        "reference_path": None,
        "description": "GPSKit 仓库的 MIT 许可测试样例，用于最小可运行功能验证。",
    },
}


class NavigationOrchestrator:
    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.llm = LLMService()
        self.supervisor = SupervisorAgent(self.registry)
        self.ingestion_agent = IngestionAgent(self.registry)
        self.quality_agent = QualityControlAgent(self.registry)
        self.strategy_agent = StrategyAgent(self.registry)
        self.ambiguity_agent = AmbiguityResolutionAgent(self.registry)
        self.integrity_agent = IntegrityMonitoringAgent(self.registry)
        self.continuity_agent = ContinuityAgent(self.registry)
        self.trajectory_agent = TrajectoryVisualizationAgent(self.registry)
        self.explanation_agent = ExplanationAgent(self.registry, llm=self.llm)
        self._last_board: Optional[Dict[str, Any]] = None

    def list_datasets(self) -> List[DatasetInfo]:
        return [
            DatasetInfo(
                name=name,
                file_path=str(item["file_path"]),
                reference_path=str(item["reference_path"]) if item["reference_path"] else None,
                description=item["description"],
            )
            for name, item in DATASET_REGISTRY.items()
        ]

    def analyze_dataset(self, dataset_name: str, baseline_length_m: float, candidate_count: int, use_llm: bool, enable_amap_geocode: bool) -> AnalysisResponse:
        if dataset_name not in DATASET_REGISTRY:
            raise ValueError(f"Unknown dataset: {dataset_name}")
        item = DATASET_REGISTRY[dataset_name]
        return self.analyze_file(
            file_path=item["file_path"],
            dataset_name=dataset_name,
            description=item["description"],
            baseline_length_m=baseline_length_m,
            candidate_count=candidate_count,
            use_llm=use_llm,
            enable_amap_geocode=enable_amap_geocode,
            reference_path=item.get("reference_path"),
        )

    def analyze_file(
        self,
        file_path: Path,
        dataset_name: str,
        description: str,
        baseline_length_m: float,
        candidate_count: int,
        use_llm: bool,
        enable_amap_geocode: bool,
        reference_path: Optional[Path] = None,
    ) -> AnalysisResponse:
        board: Dict[str, Any] = {
            "request": {
                "baseline_length_m": baseline_length_m,
                "candidate_count": candidate_count,
                "use_llm": use_llm,
                "enable_amap_geocode": enable_amap_geocode,
            },
            "dataset": {
                "name": dataset_name,
                "file_path": str(file_path),
                "reference_path": str(reference_path) if reference_path else None,
                "description": description,
            },
            "retry_round": 0,
            "agent_trace": [],
            "warnings": [],
            "optional_context": {},
            "supervisor_phase": "start",
        }

        self.supervisor.run(board)
        self.ingestion_agent.run(board)
        self.quality_agent.run(board)
        self.strategy_agent.run(board)

        while True:
            board["supervisor_phase"] = "post_strategy"
            self.supervisor.run(board)
            self.ambiguity_agent.run(board)
            self.integrity_agent.run(board)
            board["supervisor_phase"] = "post_integrity"
            self.supervisor.run(board)
            if board.get("retry_decision", {}).get("need_retry"):
                board["retry_round"] += 1
                board["warnings"].append(board["retry_decision"]["reason"])
                self.strategy_agent.run(board)
                continue
            break

        self.continuity_agent.run(board)
        self.trajectory_agent.run(board)
        if not board.get("final_epoch_results"):
            raise RuntimeError(
                "导航分析未生成最终历元结果：final_epoch_results 为空。"
                "请检查 continuity_agent 的执行链。"
            )

        summary_payload = self._build_summary_payload(board)
        board["summary_payload"] = summary_payload
        self.explanation_agent.run(board)
        summary_payload = self._build_summary_payload(board)
        board["summary_payload"] = summary_payload
        self._last_board = board

        dataset_info = DatasetInfo(
            name=dataset_name,
            file_path=str(file_path),
            description=description,
            reference_path=str(reference_path) if reference_path else None,
        )
        return AnalysisResponse(
            dataset=dataset_info,
            summary=AnalysisSummary(**summary_payload),
            epochs=self._build_epoch_results(board),
            explanation=board.get("final_explanation", ""),
            source_notes=[
                f"Processed CSV exported to: {board.get('processed_csv')}",
                "Core GNSS analysis tools are local Python tools derived from thesis logic. LLM-based explanation uses Aliyun Model Studio through its OpenAI-compatible chat interface when enabled.",
                "Core planning agents run on deterministic mandatory tool chains; LLM planning is no longer allowed to skip required navigation tools.",
                "Optional reverse geocoding uses AMap Web Service API only when enable_amap_geocode=true and AMAP_WEB_KEY is configured.",
                "Trajectory display and playback use AMap JavaScript API on the frontend when AMAP_JS_KEY is configured.",
            ],
            agent_trace=board.get("agent_trace", []),
            tool_sources=self.registry.source_map(),
            optional_context=board.get("optional_context", {}),
        )



    def get_map_config(self):
        from app.core.config import settings
        from app.models.schemas import MapConfigResponse

        enabled = bool(settings.amap_js_key)
        note = None if enabled else "未配置 AMAP_JS_KEY，前端将隐藏高德地图轨迹展示。"
        return MapConfigResponse(
            enabled=enabled,
            key=settings.amap_js_key if enabled else "",
            security_js_code=settings.amap_security_js_code if enabled else "",
            provider="amap-jsapi",
            note=note,
        )

    def answer_followup(self, question: str, use_llm: bool = True) -> FollowupResponse:
        if self._last_board is None:
            raise ValueError("No previous analysis is available. Please run an analysis first.")
        answer = self.explanation_agent.answer_followup(self._last_board, question, use_llm=use_llm)
        return FollowupResponse(answer=answer, agent_trace=[])

    def _build_epoch_results(self, board: Dict[str, Any]) -> List[EpochResult]:
        epochs = board.get("raw_epochs", [])
        quality_per_epoch = board.get("quality_per_epoch", [])
        final_epoch_results = board.get("final_epoch_results", [])
        results: List[EpochResult] = []
        for idx, epoch in enumerate(epochs):
            quality = quality_per_epoch[idx] if idx < len(quality_per_epoch) else {}
            final = final_epoch_results[idx] if idx < len(final_epoch_results) else {}
            selected = final.get("selected_candidate", {})
            results.append(
                EpochResult(
                    timestamp=epoch.timestamp,
                    latitude=epoch.latitude,
                    longitude=epoch.longitude,
                    altitude_m=epoch.altitude_m,
                    speed_knots=epoch.speed_knots,
                    course_deg=epoch.course_deg,
                    heading_raw_deg=selected.get("heading_deg"),
                    heading_smoothed_deg=final.get("smoothed_heading_deg"),
                    confidence=float(final.get("confidence", 0.0)),
                    quality_level=board.get("quality_report", {}).get("quality_level", "unknown"),
                    quality_score=float(quality.get("quality_score", 0.0)),
                    model_choice=board.get("strategy_report", {}).get("model_choice", "unknown"),
                    strategy_profile=board.get("strategy_report", {}).get("strategy_profile", "unknown"),
                    candidate_index=int(selected.get("index", 1)),
                    candidate_count=int(final.get("candidate_count", 0)),
                    separation_score=float(final.get("separation_score", 0.0)),
                    dynamic_threshold_m=float(final.get("dynamic_threshold_m", 0.0)),
                    baseline_error_m=float(selected.get("baseline_error_m", 0.0)),
                    baseline_estimate_m=float(selected.get("baseline_estimate_m", board['request']['baseline_length_m'])),
                    fix_success=bool(final.get("fix_success", False)),
                    integrity_risk=str(final.get("risk", "high")),
                    retry_round=int(board.get("retry_round", 0)),
                    explanation=self._epoch_explanation(board, quality, final, selected),
                    metrics={
                        "fix_quality": epoch.fix_quality,
                        "sats_used": epoch.sats_used,
                        "hdop": epoch.hdop,
                        "pdop": epoch.pdop,
                        "vdop": epoch.vdop,
                        "total_sats_in_view": epoch.total_sats_in_view,
                        "avg_cn0": epoch.avg_cn0,
                        "horizontal_error_m": epoch.horizontal_error_m,
                        "posterior_sigma_m": final.get("posterior_sigma_m"),
                        "jump_detected": final.get("jump_detected", False),
                    },
                )
            )
        return results

    def _epoch_explanation(self, board: Dict[str, Any], quality: Dict[str, Any], final: Dict[str, Any], selected: Dict[str, Any]) -> str:
        return (
            f"质量分数 {float(quality.get('quality_score', 0.0)):.2f}，"
            f"策略 {board.get('strategy_report', {}).get('strategy_profile', 'unknown')}，"
            f"候选 #{int(selected.get('index', 1))}，"
            f"基线误差 {float(selected.get('baseline_error_m', 0.0)):.4f} m，"
            f"风险 {str(final.get('risk', 'high'))}。"
        )

    def _build_summary_payload(self, board: Dict[str, Any]) -> Dict[str, Any]:
        final_epoch_results = board.get("final_epoch_results", [])
        epochs = board.get("raw_epochs", [])
        fix_success_count = sum(1 for item in final_epoch_results if item.get("fix_success"))
        confidence_values = [float(item.get("confidence", 0.0)) for item in final_epoch_results]
        smoothed_heading_values = [float(item.get("smoothed_heading_deg", 0.0)) for item in final_epoch_results if item.get("smoothed_heading_deg") is not None]
        speed_values = [float(epoch.speed_knots) for epoch in epochs if epoch.speed_knots is not None]
        error_values = [float(epoch.horizontal_error_m) for epoch in epochs if epoch.horizontal_error_m is not None]
        risk_distribution = Counter(item.get("risk", "unknown") for item in final_epoch_results)
        strategy_history = board.get("strategy_history", [])
        strategy_counter = Counter(strategy_history) if strategy_history else Counter({board.get('strategy_report', {}).get('strategy_profile', 'unknown'): len(final_epoch_results)})
        dominant_strategy = strategy_counter.most_common(1)[0][0] if strategy_counter else board.get("strategy_report", {}).get("strategy_profile", "unknown")
        findings = self._build_findings(board)
        return {
            "total_epochs": len(final_epoch_results),
            "valid_epochs": sum(1 for epoch in epochs if epoch.latitude is not None and epoch.longitude is not None),
            "fix_rate": round(fix_success_count / float(len(final_epoch_results) or 1), 4),
            "avg_confidence": round(sum(confidence_values) / float(len(confidence_values) or 1), 4),
            "avg_heading_deg": round(sum(smoothed_heading_values) / float(len(smoothed_heading_values) or 1), 4) if smoothed_heading_values else None,
            "avg_speed_knots": round(sum(speed_values) / float(len(speed_values) or 1), 4) if speed_values else None,
            "mean_position_error_m": round(sum(error_values) / float(len(error_values) or 1), 4) if error_values else None,
            "max_position_error_m": round(max(error_values), 4) if error_values else None,
            "model_usage": dict(strategy_counter),
            "risk_distribution": dict(risk_distribution),
            "retry_rounds": int(board.get("retry_round", 0)),
            "dominant_strategy": dominant_strategy,
            "agent_sequence": [trace.agent for trace in board.get("agent_trace", [])],
            "key_findings": findings,
        }

    def _build_findings(self, board: Dict[str, Any]) -> List[str]:
        integrity = board.get("integrity_report", {})
        quality = board.get("quality_report", {})
        strategy = board.get("strategy_report", {})
        continuity = board.get("continuity_report", {})
        findings = [
            f"总历元数 {len(board.get('final_epoch_results', []))}，固定成功率 {float(integrity.get('fix_rate', 0.0)):.2%}。",
            f"质量等级为 {quality.get('quality_level', 'unknown')}，主导问题：{'、'.join(quality.get('dominant_issues', []))}。",
            f"采用策略 {strategy.get('strategy_profile', 'unknown')}，共重试 {int(board.get('retry_round', 0))} 轮。",
            f"高风险比例 {float(integrity.get('high_risk_ratio', 0.0)):.2%}，航向跳变比率 {float(continuity.get('jump_ratio', 0.0)):.2%}。",
        ]
        if board.get("warnings"):
            findings.append("重试原因：" + "；".join(board["warnings"]))
        optional = board.get("optional_context", {})
        if optional.get("amap_regeocode", {}).get("formatted_address"):
            findings.append("数据集中心位置：" + optional["amap_regeocode"]["formatted_address"])
        trajectory = board.get("optional_context", {}).get("trajectory", {})
        if trajectory.get("stats", {}).get("track_length_m") is not None:
            findings.append(f"轨迹总长度约 {float(trajectory['stats']['track_length_m']):.1f} m，轨迹点数 {int(trajectory['stats'].get('point_count', 0))}。")
        return findings
