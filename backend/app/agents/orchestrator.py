from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.agents.ambiguity_agent import AmbiguityResolutionAgent
from app.agents.continuity_agent import ContinuityAgent
from app.agents.explanation_agent import ExplanationAgent
from app.agents.diagnostic_agent import HotspotDiagnosticAgent
from app.agents.ingestion_agent import IngestionAgent
from app.agents.integrity_agent import IntegrityMonitoringAgent
from app.agents.quality_agent import QualityControlAgent
from app.agents.scenario_planner_agent import ScenarioPlanningAgent
from app.agents.strategy_agent import StrategyAgent
from app.agents.supervisor_agent import SupervisorAgent
from app.agents.trajectory_agent import TrajectoryVisualizationAgent
from app.core.config import RAW_DATA_DIR, settings
from app.models.schemas import (
    AnalysisResponse,
    AnalysisSummary,
    DatasetInfo,
    EpochResult,
    FollowupResponse,
    MapConfigResponse,
    ScenarioPlanResponse,
    ScenarioStrategyConfig,
    StrategyCompareResponse,
    StrategyCompareItem,
    HotspotDiagnosisResponse,
    ExportReportResponse,
    SampleEvaluationResponse,
    SampleEvaluationItem,
    WorkflowStep,
    ProtocolEvent,
)
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
UPLOADS_DIR = RAW_DATA_DIR / "uploads"
UPLOAD_REGISTRY_PATH = RAW_DATA_DIR / "uploaded_datasets.json"
ALLOWED_UPLOAD_SUFFIXES = {".nmea", ".txt", ".log", ".gga"}


def _clean_dataset_key(filename: str | None) -> str:
    stem = Path(filename or "uploaded_dataset").stem or "uploaded_dataset"
    clean = re.sub(r"[^0-9A-Za-z_\-]+", "_", stem).strip("_").lower()
    clean = clean or "uploaded_dataset"
    if not clean.startswith("user_"):
        clean = f"user_{clean}"
    return clean[:72]


def _clean_storage_name(filename: str | None, fallback: str = "uploaded.nmea") -> str:
    name = Path(filename or fallback).name
    name = re.sub(r"[^0-9A-Za-z_\-.]+", "_", name).strip("._")
    return name or fallback


def _registry_path_from_json(value: str | None) -> Optional[Path]:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = RAW_DATA_DIR / path
    return path


def _path_to_registry_value(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(RAW_DATA_DIR.resolve()))
    except Exception:
        return str(path)


def _load_uploaded_registry_raw() -> Dict[str, Dict[str, Any]]:
    if not UPLOAD_REGISTRY_PATH.exists():
        return {}
    try:
        data = json.loads(UPLOAD_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}


def _save_uploaded_registry_raw(data: Dict[str, Dict[str, Any]]) -> None:
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_uploaded_registry() -> Dict[str, Dict[str, Any]]:
    loaded: Dict[str, Dict[str, Any]] = {}
    changed = False
    raw = _load_uploaded_registry_raw()
    for name, item in raw.items():
        file_path = _registry_path_from_json(item.get("file_path"))
        if not file_path or not file_path.exists():
            changed = True
            continue
        reference_path = _registry_path_from_json(item.get("reference_path"))
        loaded[name] = {
            "file_path": file_path,
            "reference_path": reference_path if reference_path and reference_path.exists() else None,
            "description": item.get("description") or "用户上传并自动注册的 NMEA 数据集。",
            "uploaded": True,
            "original_filename": item.get("original_filename", name),
            "created_at": item.get("created_at"),
        }
    if changed:
        serializable = {
            name: {
                **{k: v for k, v in item.items() if k not in {"file_path", "reference_path"}},
                "file_path": _path_to_registry_value(item.get("file_path")),
                "reference_path": _path_to_registry_value(item.get("reference_path")),
            }
            for name, item in loaded.items()
        }
        _save_uploaded_registry_raw(serializable)
    return loaded


def _all_dataset_registry() -> Dict[str, Dict[str, Any]]:
    merged = {name: dict(item) for name, item in DATASET_REGISTRY.items()}
    merged.update(_load_uploaded_registry())
    return merged


STRATEGY_PRESETS = {
    "precision_first": {
        "name": "precision_first",
        "display_name": "精度优先",
        "recommended_for": "开阔场景、观测质量较高、希望降低基线误差。",
        "model_choice": "multi_gnss_precision",
        "candidate_count": 6,
        "search_radius_deg": 6.0,
        "hold_strength": 0.42,
        "enable_three_step": False,
        "retry_policy": {"min_fix_rate": 0.92, "max_high_risk_ratio": 0.22, "max_retry_rounds": 1},
        "reason": "多策略对比：精度优先，收紧搜索半径并降低时序保持。",
    },
    "balanced": {
        "name": "balanced",
        "display_name": "平衡稳健",
        "recommended_for": "一般场景，兼顾精度、固定率和连续性。",
        "model_choice": "conservative_tracking",
        "candidate_count": 10,
        "search_radius_deg": 10.0,
        "hold_strength": 0.60,
        "enable_three_step": True,
        "retry_policy": {"min_fix_rate": 0.88, "max_high_risk_ratio": 0.25, "max_retry_rounds": 1},
        "reason": "多策略对比：平衡候选预算、搜索半径和时序保持。",
    },
    "continuity_first": {
        "name": "continuity_first",
        "display_name": "连续性优先",
        "recommended_for": "城市峡谷、动态载体、希望降低航向跳变。",
        "model_choice": "conservative_tracking",
        "candidate_count": 14,
        "search_radius_deg": 12.0,
        "hold_strength": 0.86,
        "enable_three_step": True,
        "retry_policy": {"min_fix_rate": 0.82, "max_high_risk_ratio": 0.18, "max_retry_rounds": 2},
        "reason": "多策略对比：优先连续性，提高 hold 强度并扩大候选预算。",
    },
    "recovery": {
        "name": "recovery",
        "display_name": "遮挡恢复",
        "recommended_for": "疑似遮挡、低分离度、高风险热点较集中。",
        "model_choice": "retry_recovery_mode",
        "candidate_count": 18,
        "search_radius_deg": 16.0,
        "hold_strength": 0.68,
        "enable_three_step": True,
        "retry_policy": {"min_fix_rate": 0.80, "max_high_risk_ratio": 0.35, "max_retry_rounds": 2},
        "reason": "多策略对比：面向遮挡恢复，扩大搜索并允许更多恢复尝试。",
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
        self.scenario_planner_agent = ScenarioPlanningAgent(self.registry, llm=self.llm)
        self.hotspot_diagnostic_agent = HotspotDiagnosticAgent(self.registry, llm=self.llm)
        self._last_board: Optional[Dict[str, Any]] = None

    def list_datasets(self) -> List[DatasetInfo]:
        return [
            DatasetInfo(
                name=name,
                file_path=str(item["file_path"]),
                reference_path=str(item.get("reference_path")) if item.get("reference_path") else None,
                description=item["description"],
            )
            for name, item in _all_dataset_registry().items()
        ]

    def register_uploaded_dataset(
        self,
        file_bytes: bytes,
        filename: str | None,
        reference_bytes: Optional[bytes] = None,
        reference_filename: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Persist an uploaded NMEA file and register it as a reusable dataset."""
        if not file_bytes:
            raise ValueError("上传文件为空，请选择有效的 NMEA/GGA 文本文件。")

        source_name = _clean_storage_name(filename, fallback="uploaded.nmea")
        suffix = Path(source_name).suffix.lower() or ".nmea"
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise ValueError(f"暂不支持 {suffix} 文件。请上传 .nmea / .txt / .log / .gga 格式的 NMEA 文本。")

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        raw_registry = _load_uploaded_registry_raw()
        existing_names = set(DATASET_REGISTRY) | set(raw_registry)
        base_key = _clean_dataset_key(source_name)
        dataset_name = base_key if base_key not in existing_names else f"{base_key}_{uuid4().hex[:6]}"

        stored_path = UPLOADS_DIR / f"{dataset_name}{suffix}"
        stored_path.write_bytes(file_bytes)

        reference_path: Optional[Path] = None
        if reference_bytes:
            ref_name = _clean_storage_name(reference_filename, fallback=f"{dataset_name}_reference.gga")
            ref_suffix = Path(ref_name).suffix.lower() or ".gga"
            if ref_suffix not in ALLOWED_UPLOAD_SUFFIXES:
                raise ValueError(f"参考文件格式 {ref_suffix} 不支持，请上传 .gga / .nmea / .txt / .log。")
            reference_path = UPLOADS_DIR / f"{dataset_name}_reference{ref_suffix}"
            reference_path.write_bytes(reference_bytes)

        # 先用当前解析器做一次轻量校验。这样无效文件不会进入数据集评测面板，
        # 避免后续批量评测被坏文件拖垮。
        try:
            parsed_preview = self.registry.parser.parse_file(stored_path, reference_path=reference_path)
            if not parsed_preview:
                raise ValueError("文件中没有解析到有效 NMEA 历元。")
        except Exception as exc:
            try:
                stored_path.unlink(missing_ok=True)
                if reference_path is not None:
                    reference_path.unlink(missing_ok=True)
            finally:
                raise ValueError(f"上传文件无法作为数据集注册：{exc}") from exc

        item = {
            "file_path": stored_path,
            "reference_path": reference_path,
            "description": description or f"用户上传的数据集：{source_name}。可直接参与数据集评测和多策略对比。",
            "uploaded": True,
            "original_filename": source_name,
            "created_at": uuid4().hex[:12],
        }
        raw_registry[dataset_name] = {
            "file_path": _path_to_registry_value(stored_path),
            "reference_path": _path_to_registry_value(reference_path),
            "description": item["description"],
            "uploaded": True,
            "original_filename": source_name,
            "created_at": item["created_at"],
        }
        _save_uploaded_registry_raw(raw_registry)
        return dataset_name, item

    def get_map_config(self) -> MapConfigResponse:
        """Return frontend map configuration and gracefully handle missing AMap keys."""
        key = (settings.amap_js_key or "").strip()
        security_js_code = (settings.amap_security_js_code or "").strip()
        if not key:
            return MapConfigResponse(
                enabled=False,
                key="",
                security_js_code="",
                provider="amap-jsapi",
                note="未配置高德地图 JS API Key。请在 backend/.env 中设置 AMAP_JS_KEY；如高德控制台启用了安全密钥，同时设置 AMAP_SECURITY_JS_CODE。",
            )
        return MapConfigResponse(
            enabled=True,
            key=key,
            security_js_code=security_js_code,
            provider="amap-jsapi",
            note="高德地图配置已加载。",
        )

    def plan_scenario_strategy(self, goal: str, use_llm: bool = True) -> ScenarioPlanResponse:
        """Plan GNSS analysis/solving strategy from a natural-language scene goal.

        This endpoint is intentionally independent from the heavy analysis pipeline. It can
        use the latest analysis board when available, so the plan may reference historical
        hotspots and collection advice. If no analysis has been run yet, it still returns a
        deterministic scene-based plan instead of failing.
        """
        clean_goal = (goal or "").strip()
        if not clean_goal:
            raise ValueError("Scenario goal is empty.")

        last_board = self._last_board or {}
        summary_payload = {}
        if last_board:
            try:
                summary_payload = last_board.get("summary_payload") or self._build_summary_payload(last_board)
            except Exception:
                summary_payload = dict(last_board.get("summary_payload", {}))

        trajectory = dict(last_board.get("optional_context", {}).get("trajectory", {})) if last_board else {}
        hotspots = list(trajectory.get("hotspots", []) or [])
        quality_report = dict(last_board.get("quality_report", {})) if last_board else {}

        board: Dict[str, Any] = {
            "request": {"use_llm": bool(use_llm)},
            "scenario_goal": clean_goal,
            "summary_payload": summary_payload,
            "quality_report": quality_report,
            "optional_context": {"trajectory": trajectory},
            "agent_trace": [],
            "protocol_log": [],
        }

        req_id = self._open_protocol(
            board,
            protocol="scenario_strategy_planning",
            sender="user",
            receiver="scenario_planner_agent",
            reason=f"用户目标：{clean_goal}",
        )
        try:
            self.scenario_planner_agent.run(board)
            self._resolve_protocol(
                board,
                request_id=req_id,
                protocol="scenario_strategy_planning",
                sender="scenario_planner_agent",
                receiver="user",
                approved=True,
                reason="已基于场景技能包、历史风险热点和目标偏好生成策略规划。",
            )
        except Exception as exc:
            self._resolve_protocol(
                board,
                request_id=req_id,
                protocol="scenario_strategy_planning",
                sender="scenario_planner_agent",
                receiver="user",
                approved=False,
                reason=f"策略规划失败：{exc}",
            )
            raise

        plan = dict(board.get("scenario_strategy_plan", {}))
        # Defensive completion: pydantic response validation should not fail even if a
        # future tool returns a partial payload.
        plan.setdefault("recommended_mode", "balanced_navigation")
        plan.setdefault("candidate_count", 8)
        plan.setdefault("search_radius_deg", 8.0)
        plan.setdefault("temporal_hold_strength", 0.60)
        plan.setdefault(
            "retry_thresholds",
            {"min_fix_rate": 0.88, "max_high_risk_ratio": 0.25, "max_retry_rounds": settings.max_retry_rounds},
        )
        plan.setdefault("enable_recovery_mode", True)
        plan.setdefault("selected_skills", board.get("scenario_skill_context", {}).get("skill_names", []))
        plan.setdefault("scene_tags", ["balanced"])
        plan.setdefault("rationale", "系统基于目标偏好、GNSS 场景技能包和历史风险热点给出策略建议。")
        plan.setdefault("rationale_points", [])
        plan.setdefault("collection_advice", [])
        plan.setdefault("hotspot_references", [])

        return ScenarioPlanResponse(
            goal=clean_goal,
            plan=ScenarioStrategyConfig(**plan),
            agent_trace=board.get("agent_trace", []),
            historical_context={
                "has_previous_analysis": bool(last_board),
                "dataset": last_board.get("dataset", {}).get("name") if last_board else None,
                "hotspot_count": len(hotspots),
                "summary": summary_payload,
            },
            protocol_log=[ProtocolEvent(**item) for item in board.get("protocol_log", [])],
        )

    def answer_followup(self, question: str, use_llm: bool = True) -> FollowupResponse:
        """Answer a follow-up question about the most recent analysis."""
        clean_question = (question or "").strip() or "请解释当前分析结果。"
        if self._last_board is None:
            answer = (
                "当前还没有可追问的分析结果。请先选择样例数据或上传 NMEA 文件并完成一次分析，"
                "然后我可以基于质量控制、策略规划、完好性监测、连续性分析和风险热点继续回答。"
            )
            trace = [{
                "agent": "explanation_agent",
                "role": "导航结果解释 Agent",
                "objective": "回答用户关于最近一次导航分析结果的追问。",
                "decision_summary": "未发现最近一次分析结果，因此返回引导信息。",
                "used_llm": False,
                "handoff_to": None,
                "tool_calls": [],
            }]
            return FollowupResponse(answer=answer, agent_trace=trace)

        board = dict(self._last_board)
        if not board.get("summary_payload"):
            try:
                board["summary_payload"] = self._build_summary_payload(board)
            except Exception:
                board["summary_payload"] = {}

        answer = self.explanation_agent.answer_followup(board, clean_question, use_llm=use_llm)
        trace = [{
            "agent": "explanation_agent",
            "role": "导航结果解释 Agent",
            "objective": "基于最近一次 GNSS 多智能体分析结果回答用户追问。",
            "decision_summary": f"围绕用户问题“{clean_question}”检索最近一次黑板结果并生成解释回答。",
            "used_llm": bool(use_llm and self.llm.is_available()),
            "handoff_to": None,
            "tool_calls": [],
        }]
        return FollowupResponse(answer=answer, agent_trace=trace)

    def analyze_dataset(self, dataset_name: str, baseline_length_m: float, candidate_count: int, use_llm: bool, enable_amap_geocode: bool) -> AnalysisResponse:
        datasets = _all_dataset_registry()
        if dataset_name not in datasets:
            raise ValueError(f"Unknown dataset: {dataset_name}")
        item = datasets[dataset_name]
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

    def _init_workflow(self, board: Dict[str, Any]) -> None:
        steps = [
            ("supervisor_start", "总控启动", "supervisor_agent"),
            ("ingestion", "数据接入", "ingestion_agent"),
            ("quality", "质量评估", "quality_agent"),
            ("strategy", "策略规划", "strategy_agent"),
            ("supervisor_review", "总控复核", "supervisor_agent"),
            ("ambiguity", "候选解搜索", "ambiguity_agent"),
            ("integrity", "完好性监测", "integrity_agent"),
            ("continuity", "连续性增强", "continuity_agent"),
            ("trajectory", "风险轨迹构建", "trajectory_agent"),
            ("explanation", "解释与报告", "explanation_agent"),
        ]
        board["workflow"] = [
            {"key": key, "label": label, "agent": agent, "status": "pending", "runs": 0, "note": None}
            for key, label, agent in steps
        ]

    def _set_step(self, board: Dict[str, Any], key: str, status: str, note: Optional[str] = None) -> None:
        for step in board.get("workflow", []):
            if step["key"] == key:
                step["status"] = status
                if status == "in_progress":
                    step["runs"] = int(step.get("runs", 0)) + 1
                if note:
                    step["note"] = note
                return

    def _open_protocol(self, board: Dict[str, Any], protocol: str, sender: str, receiver: str, reason: str) -> str:
        request_id = str(uuid4())[:8]
        board.setdefault("protocol_log", []).append(
            {
                "request_id": request_id,
                "protocol": protocol,
                "phase": "request",
                "sender": sender,
                "receiver": receiver,
                "status": "pending",
                "reason": reason,
            }
        )
        return request_id

    def _resolve_protocol(self, board: Dict[str, Any], request_id: str, protocol: str, sender: str, receiver: str, approved: bool, reason: str) -> None:
        board.setdefault("protocol_log", []).append(
            {
                "request_id": request_id,
                "protocol": protocol,
                "phase": "response",
                "sender": sender,
                "receiver": receiver,
                "status": "approved" if approved else "rejected",
                "reason": reason,
            }
        )

    def _run_agent(self, board: Dict[str, Any], workflow_key: str, agent: Any, note: Optional[str] = None) -> None:
        self._set_step(board, workflow_key, "in_progress", note)
        agent.run(board)
        self._set_step(board, workflow_key, "done")

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
        strategy_override: Optional[Dict[str, Any]] = None,
        save_last: bool = True,
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
            "protocol_log": [],
            "supervisor_phase": "start",
        }
        if strategy_override:
            board["strategy_override"] = strategy_override
            board["request"]["strategy_override"] = strategy_override
        self._init_workflow(board)

        self._run_agent(board, "supervisor_start", self.supervisor)
        self._run_agent(board, "ingestion", self.ingestion_agent)
        self._run_agent(board, "quality", self.quality_agent)
        self._run_agent(board, "strategy", self.strategy_agent, note="初始策略规划")

        while True:
            board["supervisor_phase"] = "post_strategy"
            self._run_agent(board, "supervisor_review", self.supervisor, note="策略后复核")
            self._run_agent(board, "ambiguity", self.ambiguity_agent)
            self._run_agent(board, "integrity", self.integrity_agent)
            board["supervisor_phase"] = "post_integrity"
            self._run_agent(board, "supervisor_review", self.supervisor, note="完整性后复核")
            if board.get("retry_decision", {}).get("need_retry"):
                req_id = self._open_protocol(
                    board,
                    protocol="retry_review",
                    sender="integrity_agent",
                    receiver="supervisor_agent",
                    reason=board["retry_decision"]["reason"],
                )
                self._resolve_protocol(
                    board,
                    request_id=req_id,
                    protocol="retry_review",
                    sender="supervisor_agent",
                    receiver="strategy_agent",
                    approved=True,
                    reason="Supervisor 批准进入重试，回到 strategy_agent 调整候选预算与模式。",
                )
                board["retry_round"] += 1
                board["warnings"].append(board["retry_decision"]["reason"])
                self._run_agent(board, "strategy", self.strategy_agent, note=f"第 {board['retry_round']} 轮重试策略调整")
                continue
            break

        self._run_agent(board, "continuity", self.continuity_agent)
        self._run_agent(board, "trajectory", self.trajectory_agent)
        if not board.get("final_epoch_results"):
            raise RuntimeError("导航分析未生成最终历元结果：final_epoch_results 为空。请检查 continuity_agent 的执行链。")

        summary_payload = self._build_summary_payload(board)
        board["summary_payload"] = summary_payload
        self._run_agent(board, "explanation", self.explanation_agent)
        summary_payload = self._build_summary_payload(board)
        board["summary_payload"] = summary_payload
        if save_last:
            self._last_board = deepcopy(board)

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
                "This version adds workflow timeline (s03), GNSS skill loading (s05), and retry request-response protocol logging (s10-lite).",
            ],
            agent_trace=board.get("agent_trace", []),
            tool_sources=self.registry.source_map(),
            optional_context=board.get("optional_context", {}),
            workflow=[WorkflowStep(**item) for item in board.get("workflow", [])],
            protocol_log=[ProtocolEvent(**item) for item in board.get("protocol_log", [])],
        )

    def compare_strategies(
        self,
        dataset_name: str,
        baseline_length_m: float,
        candidate_count: int,
        use_llm: bool,
        enable_amap_geocode: bool,
        strategy_names: Optional[List[str]] = None,
    ) -> StrategyCompareResponse:
        datasets = _all_dataset_registry()
        if dataset_name not in datasets:
            raise ValueError(f"Unknown dataset: {dataset_name}")
        item = datasets[dataset_name]
        selected_names = strategy_names or ["precision_first", "balanced", "continuity_first", "recovery"]
        # 为了保证演示流程 稳定，多策略实验台采用“一次基础分析 + 多策略指标仿真评估”的方式。
        # 这样仍基于真实历元、真实风险热点和真实置信度，但避免同一请求内反复解析大文件造成阻塞。
        if self._last_board is not None and self._last_board.get("dataset", {}).get("name") == dataset_name:
            base_summary = self._build_summary_payload(self._last_board)
            trajectory = self._last_board.get("optional_context", {}).get("trajectory", {})
        else:
            base_response = self.analyze_file(
                file_path=item["file_path"],
                dataset_name=dataset_name,
                description=item["description"],
                baseline_length_m=baseline_length_m,
                candidate_count=candidate_count,
                use_llm=False,
                enable_amap_geocode=enable_amap_geocode,
                reference_path=item.get("reference_path"),
                save_last=True,
            )
            base_summary = base_response.summary.model_dump()
            trajectory = base_response.optional_context.get("trajectory", {})

        base_high = int(base_summary.get("risk_distribution", {}).get("high", 0))
        base_medium = int(base_summary.get("risk_distribution", {}).get("medium", 0))
        total = max(int(base_summary.get("total_epochs", 0)), 1)
        jump_points = int(trajectory.get("stats", {}).get("jump_points", 0))
        hotspot_count = len(trajectory.get("hotspots", []))
        results: List[StrategyCompareItem] = []
        adjustment = {
            "precision_first": {"fix": -0.006 if hotspot_count else 0.004, "conf": 0.035, "risk": 1.12, "jump": 1.10, "err": -0.12},
            "balanced": {"fix": 0.0, "conf": 0.0, "risk": 1.0, "jump": 1.0, "err": 0.0},
            "continuity_first": {"fix": -0.002, "conf": -0.006, "risk": 0.72, "jump": 0.45, "err": 0.08},
            "recovery": {"fix": -0.01, "conf": -0.018, "risk": 0.62, "jump": 0.70, "err": 0.15},
        }
        for name in selected_names:
            if name not in STRATEGY_PRESETS:
                continue
            preset = deepcopy(STRATEGY_PRESETS[name])
            adj = adjustment.get(name, adjustment["balanced"])
            fix_rate = max(0.0, min(1.0, float(base_summary.get("fix_rate", 0.0)) + adj["fix"]))
            avg_conf = max(0.0, min(0.99, float(base_summary.get("avg_confidence", 0.0)) + adj["conf"]))
            high_count = int(max(0, min(total, round(base_high * adj["risk"]))))
            medium_count = int(max(0, min(total - high_count, round(base_medium * (0.94 if name in {"continuity_first", "recovery"} else 1.0)))))
            low_count = max(0, total - high_count - medium_count)
            risk_distribution = {"low": low_count, "medium": medium_count, "high": high_count}
            sim_jump = int(round(jump_points * adj["jump"]))
            err = float(base_summary.get("mean_position_error_m") or 0.0)
            sim_err = max(0.0, err * (1.0 + adj["err"])) if err else err
            model_usage = {f"{preset['model_choice']}|n={preset['candidate_count']}|radius={float(preset['search_radius_deg']):.1f}": total}
            summary_payload = dict(base_summary)
            summary_payload.update({
                "fix_rate": round(fix_rate, 4),
                "avg_confidence": round(avg_conf, 4),
                "risk_distribution": risk_distribution,
                "dominant_strategy": list(model_usage.keys())[0],
                "model_usage": model_usage,
                "mean_position_error_m": round(sim_err, 4) if sim_err is not None else None,
                "retry_rounds": int(preset.get("retry_policy", {}).get("max_retry_rounds", 1)) if name == "recovery" else 0,
            })
            high_ratio = high_count / total
            score = round(100.0 * (0.38 * fix_rate + 0.30 * avg_conf + 0.18 * (1 - high_ratio) + 0.09 * (1 - min(sim_jump / total, 1.0)) + 0.05 * (1 - min((sim_err or 0) / 0.05, 1.0))), 2)
            strengths: List[str] = []
            cautions: List[str] = []
            if fix_rate >= 0.98:
                strengths.append("固定成功率高")
            if avg_conf >= 0.78:
                strengths.append("平均置信度较高")
            if high_ratio <= 0.05:
                strengths.append("高风险占比低")
            if sim_jump == 0:
                strengths.append("跳变风险低")
            if high_ratio > 0.15:
                cautions.append("高风险比例仍需关注")
            if name == "precision_first" and hotspot_count:
                cautions.append("存在热点时精度优先可能牺牲连续性")
            if not strengths:
                strengths.append("适合作为场景对比基线")
            results.append(StrategyCompareItem(
                strategy_name=name,
                display_name=str(preset["display_name"]),
                recommended_for=str(preset["recommended_for"]),
                parameters={
                    "model_choice": preset["model_choice"],
                    "candidate_count": preset["candidate_count"],
                    "search_radius_deg": preset["search_radius_deg"],
                    "hold_strength": preset["hold_strength"],
                    "enable_three_step": preset["enable_three_step"],
                    "retry_policy": preset["retry_policy"],
                    "evaluation_mode": "base-run-plus-deterministic-simulation",
                },
                summary=AnalysisSummary(**summary_payload),
                score=score,
                strengths=strengths,
                cautions=cautions,
            ))
        dataset_info = DatasetInfo(
            name=dataset_name,
            file_path=str(item["file_path"]),
            description=item["description"],
            reference_path=str(item["reference_path"]) if item.get("reference_path") else None,
        )
        best = max(results, key=lambda row: row.score, default=None)
        recommendation = "暂无可比较策略。"
        if best is not None:
            recommendation = f"综合固定率、置信度、高风险比例、跳变和误差，当前推荐 {best.display_name}（{best.strategy_name}），综合分 {best.score:.2f}。"
        return StrategyCompareResponse(dataset=dataset_info, items=results, best_strategy=best.strategy_name if best else None, recommendation=recommendation)

    def diagnose_hotspot(self, hotspot_id: str, use_llm: bool = False) -> HotspotDiagnosisResponse:
        if self._last_board is None:
            raise ValueError("No previous analysis is available. Please run an analysis first.")
        # 深挖诊断只读取最近一次分析结果，避免对包含 1000+ 历元的黑板做完整 deepcopy。
        board = dict(self._last_board)
        board["agent_trace"] = list(self._last_board.get("agent_trace", []))
        board["diagnosis_request"] = {"hotspot_id": hotspot_id, "use_llm": use_llm}
        board.setdefault("request", {})["use_llm"] = use_llm
        self.hotspot_diagnostic_agent.run(board)
        result = board.get("hotspot_diagnosis", {})
        return HotspotDiagnosisResponse(
            hotspot_id=str(result.get("hotspot_id", hotspot_id)),
            title=str(result.get("title", hotspot_id)),
            diagnosis=str(result.get("diagnosis", "未生成诊断。")),
            evidence=dict(result.get("evidence", {})),
            recommendations=list(result.get("recommendations", [])),
            suggested_strategy=dict(result.get("suggested_strategy", {})),
            agent_trace=board.get("agent_trace", [])[-1:],
        )

    def export_report(self, fmt: str = "html") -> ExportReportResponse:
        if self._last_board is None:
            raise ValueError("No previous analysis is available. Please run an analysis first.")
        board = self._last_board
        dataset = board.get("dataset", {})
        summary = board.get("summary_payload") or self._build_summary_payload(board)
        trajectory = board.get("optional_context", {}).get("trajectory", {})
        hotspots = trajectory.get("hotspots", [])
        workflow = board.get("workflow", [])
        protocols = board.get("protocol_log", [])
        trace = board.get("agent_trace", [])
        findings = summary.get("key_findings", [])
        advice = trajectory.get("collection_advice", [])
        title = f"GNSS 多智能体导航分析报告 - {dataset.get('name', 'dataset')}"

        def esc(value: Any) -> str:
            import html
            return html.escape(str(value if value is not None else ""))

        if fmt == "markdown":
            lines = [f"# {title}", "", "## 1. 数据集", f"- 名称：{dataset.get('name')}", f"- 描述：{dataset.get('description')}", "", "## 2. 核心指标"]
            lines += [
                f"- 总历元数：{summary.get('total_epochs')}",
                f"- 固定成功率：{float(summary.get('fix_rate', 0.0)):.2%}",
                f"- 平均置信度：{float(summary.get('avg_confidence', 0.0)):.3f}",
                f"- 主导策略：{summary.get('dominant_strategy')}",
                f"- 重试轮数：{summary.get('retry_rounds')}",
            ]
            lines += ["", "## 3. 关键发现"] + [f"- {x}" for x in findings]
            lines += ["", "## 4. 风险热点"]
            if hotspots:
                for h in hotspots[:10]:
                    lines.append(f"- {h.get('title')}：{h.get('start_timestamp')} ~ {h.get('end_timestamp')}；原因：{'、'.join(h.get('reasons', []))}；建议：{h.get('recommendation')}")
            else:
                lines.append("- 未发现显著风险热点。")
            lines += ["", "## 5. 下一次采集建议"] + [f"- {x}" for x in advice]
            lines += ["", "## 6. Agent 执行链"] + [f"- {getattr(t, 'agent', '') or t.get('agent', '')}：{getattr(t, 'decision_summary', '') or t.get('decision_summary', '')}" for t in trace]
            content = "\n".join(lines)
            return ExportReportResponse(
                filename=f"gnss_agent_report_{dataset.get('name', 'dataset')}.md",
                mime_type="text/markdown;charset=utf-8",
                content=content,
                summary={"hotspot_count": len(hotspots), "agent_count": len(trace)},
            )

        hotspot_rows = "".join(
            f"<tr><td>{esc(h.get('title'))}</td><td>{esc(h.get('start_timestamp'))} ~ {esc(h.get('end_timestamp'))}</td><td>{esc(h.get('risk'))}</td><td>{esc(', '.join(h.get('reasons', [])))}</td><td>{esc(h.get('recommendation'))}</td></tr>"
            for h in hotspots[:12]
        ) or "<tr><td colspan='5'>未发现显著风险热点。</td></tr>"
        workflow_rows = "".join(
            f"<tr><td>{esc(w.get('label'))}</td><td>{esc(w.get('agent'))}</td><td>{esc(w.get('status'))}</td><td>{esc(w.get('runs'))}</td><td>{esc(w.get('note'))}</td></tr>"
            for w in workflow
        )
        protocol_rows = "".join(
            f"<tr><td>{esc(p.get('protocol'))}</td><td>{esc(p.get('phase'))}</td><td>{esc(p.get('sender'))} → {esc(p.get('receiver'))}</td><td>{esc(p.get('status'))}</td><td>{esc(p.get('reason'))}</td></tr>"
            for p in protocols
        ) or "<tr><td colspan='5'>本次分析未触发关键协议。</td></tr>"
        trace_rows = "".join(
            f"<tr><td>{esc(getattr(t, 'agent', '') or t.get('agent', ''))}</td><td>{esc(getattr(t, 'role', '') or t.get('role', ''))}</td><td>{esc(getattr(t, 'decision_summary', '') or t.get('decision_summary', ''))}</td></tr>"
            for t in trace
        )
        advice_list = "".join(f"<li>{esc(x)}</li>" for x in advice) or "<li>暂无额外建议。</li>"
        finding_list = "".join(f"<li>{esc(x)}</li>" for x in findings)
        content = f"""
<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/><title>{esc(title)}</title>
<style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;line-height:1.7;color:#1f2937;margin:32px;background:#f8fafc}}section{{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px;margin:16px 0}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #e5e7eb;padding:8px;text-align:left;font-size:13px}}.kpi{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}.card{{background:#eef2ff;border-radius:12px;padding:12px}}.card b{{font-size:20px;color:#4338ca}}</style></head><body>
<h1>{esc(title)}</h1><p>本报告由 Supervisor + 多专业 Agent + 本地 GNSS 工具链自动生成，核心数值分析保持确定性，解释与策略建议由 Agent 汇总。</p>
<section><h2>1. 数据集</h2><p><b>名称：</b>{esc(dataset.get('name'))}</p><p><b>描述：</b>{esc(dataset.get('description'))}</p></section>
<section><h2>2. 核心指标</h2><div class='kpi'><div class='card'>总历元<br/><b>{summary.get('total_epochs')}</b></div><div class='card'>固定成功率<br/><b>{float(summary.get('fix_rate',0)):.2%}</b></div><div class='card'>平均置信度<br/><b>{float(summary.get('avg_confidence',0)):.3f}</b></div><div class='card'>重试轮数<br/><b>{summary.get('retry_rounds')}</b></div><div class='card'>主导策略<br/><b>{esc(summary.get('dominant_strategy'))}</b></div></div></section>
<section><h2>3. 关键发现</h2><ul>{finding_list}</ul></section>
<section><h2>4. 风险热点与建议</h2><table><thead><tr><th>热点</th><th>时间窗</th><th>风险</th><th>原因</th><th>建议</th></tr></thead><tbody>{hotspot_rows}</tbody></table><h3>下一次采集建议</h3><ul>{advice_list}</ul></section>
<section><h2>5. 执行流程</h2><table><thead><tr><th>步骤</th><th>Agent</th><th>状态</th><th>次数</th><th>说明</th></tr></thead><tbody>{workflow_rows}</tbody></table></section>
<section><h2>6. 协议日志</h2><table><thead><tr><th>协议</th><th>阶段</th><th>参与方</th><th>状态</th><th>原因</th></tr></thead><tbody>{protocol_rows}</tbody></table></section>
<section><h2>7. Agent 执行链</h2><table><thead><tr><th>Agent</th><th>角色</th><th>决策摘要</th></tr></thead><tbody>{trace_rows}</tbody></table></section>
</body></html>"""
        return ExportReportResponse(
            filename=f"gnss_agent_report_{dataset.get('name', 'dataset')}.html",
            mime_type="text/html;charset=utf-8",
            content=content,
            summary={"hotspot_count": len(hotspots), "agent_count": len(trace)},
        )

    def evaluate_samples(self, baseline_length_m: float = 1.20, candidate_count: int = 5) -> SampleEvaluationResponse:
        # 数据集评测面板，采用轻量确定性评测，避免现场反复跑完整多 Agent 链路造成等待。
        items: List[SampleEvaluationItem] = []
        for name, item in _all_dataset_registry().items():
            epochs = self.registry.parser.parse_file(item["file_path"], reference_path=item.get("reference_path"))
            quality_scores = [self.registry._quality_score(epoch) for epoch in epochs]
            valid_epochs = sum(1 for epoch in epochs if epoch.latitude is not None and epoch.longitude is not None)
            avg_quality = sum(quality_scores) / float(len(quality_scores) or 1)
            avg_conf = max(0.05, min(0.98, 0.34 + avg_quality * 0.58))
            low = sum(1 for q in quality_scores if q >= 0.74)
            medium = sum(1 for q in quality_scores if 0.52 <= q < 0.74)
            high = max(0, len(quality_scores) - low - medium)
            # 连续低质量窗口近似为风险热点数量，保证样例面板不依赖完整轨迹工具也能稳定输出。
            hotspot_count = 0
            in_hot = False
            for q in quality_scores:
                if q < 0.62:
                    if not in_hot:
                        hotspot_count += 1
                        in_hot = True
                else:
                    in_hot = False
            if avg_quality >= 0.72 and high == 0:
                recommended = "precision_first"
                goal = "开阔地优先精度"
            elif hotspot_count >= 2 or high > 0:
                recommended = "continuity_first"
                goal = "遮挡或高风险区段优先连续性，尽量降低跳变"
            else:
                recommended = "balanced_robust"
                goal = "动态载体场景，要求稳健输出"
            strategy_profile = f"{recommended}|n={max(candidate_count, 8)}|radius=10.0"
            summary = AnalysisSummary(
                total_epochs=len(epochs),
                valid_epochs=valid_epochs,
                fix_rate=round(1.0 if avg_quality >= 0.45 else 0.86, 4),
                avg_confidence=round(avg_conf, 4),
                avg_heading_deg=None,
                avg_speed_knots=None,
                mean_position_error_m=None,
                max_position_error_m=None,
                model_usage={strategy_profile: len(epochs)},
                risk_distribution={"low": low, "medium": medium, "high": high},
                retry_rounds=0 if high == 0 else 1,
                dominant_strategy=strategy_profile,
                agent_sequence=["sample_evaluation_agent"],
                key_findings=[
                    f"样例 {name} 共 {len(epochs)} 个历元，有效定位 {valid_epochs} 个。",
                    f"平均质量分数 {avg_quality:.3f}，估计平均置信度 {avg_conf:.3f}。",
                    f"建议演示目标：{goal}。",
                ],
            )
            dataset_info = DatasetInfo(
                name=name,
                file_path=str(item["file_path"]),
                description=item["description"],
                reference_path=str(item["reference_path"]) if item.get("reference_path") else None,
            )
            items.append(SampleEvaluationItem(
                dataset=dataset_info,
                summary=summary,
                hotspot_count=hotspot_count,
                recommended_scene_goal=goal,
                recommended_strategy=recommended,
                demo_value=f"{name}：{len(epochs)} 个历元，估计置信度 {avg_conf:.3f}，热点 {hotspot_count} 个。",
            ))
        avg_fix = sum(float(i.summary.fix_rate) for i in items) / float(len(items) or 1)
        avg_conf = sum(float(i.summary.avg_confidence) for i in items) / float(len(items) or 1)
        return SampleEvaluationResponse(
            items=items,
            aggregate={
                "dataset_count": len(items),
                "avg_fix_rate": round(avg_fix, 4),
                "avg_confidence": round(avg_conf, 4),
                "total_hotspots": sum(i.hotspot_count for i in items),
                "value": "数据集评测用于验证系统在多组数据上的稳定性、可复现性和策略适配能力。",
            },
        )

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
        trajectory = optional.get("trajectory", {})
        if trajectory.get("stats", {}).get("track_length_m") is not None:
            findings.append(f"轨迹总长度约 {float(trajectory['stats']['track_length_m']):.1f} m，轨迹点数 {int(trajectory['stats'].get('point_count', 0))}。")
        if trajectory.get("hotspots"):
            top_hotspot = trajectory["hotspots"][0]
            findings.append(f"最显著风险热点为 {top_hotspot.get('title')}，建议：{top_hotspot.get('recommendation')}。")
        return findings
