from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DatasetInfo(BaseModel):
    name: str
    file_path: str
    description: str
    reference_path: Optional[str] = None


class AnalysisRequest(BaseModel):
    dataset_name: str = Field(default="google_mtv_local1")
    baseline_length_m: float = Field(default=1.20, ge=0.1, le=20.0)
    candidate_count: int = Field(default=5, ge=3, le=50)
    use_llm: bool = False
    enable_amap_geocode: bool = False


class FollowupRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    use_llm: bool = True


class ScenarioPlanRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=500)
    use_llm: bool = True


class ToolCallRecord(BaseModel):
    tool: str
    arguments: Dict[str, Any]
    source: str = "local"
    result_summary: str


class AgentTrace(BaseModel):
    agent: str
    role: str
    objective: str
    decision_summary: str
    used_llm: bool
    handoff_to: Optional[str] = None
    tool_calls: List[ToolCallRecord]


class WorkflowStep(BaseModel):
    key: str
    label: str
    agent: str
    status: str
    runs: int = 0
    note: Optional[str] = None


class ProtocolEvent(BaseModel):
    request_id: str
    protocol: str
    phase: str
    sender: str
    receiver: str
    status: str
    reason: Optional[str] = None


class EpochResult(BaseModel):
    timestamp: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    speed_knots: Optional[float] = None
    course_deg: Optional[float] = None
    heading_raw_deg: Optional[float] = None
    heading_smoothed_deg: Optional[float] = None
    confidence: float
    quality_level: str
    quality_score: float
    model_choice: str
    strategy_profile: str
    candidate_index: int
    candidate_count: int
    separation_score: float
    dynamic_threshold_m: float
    baseline_error_m: float
    baseline_estimate_m: float
    fix_success: bool
    integrity_risk: str
    retry_round: int
    explanation: str
    metrics: Dict[str, Any]


class AnalysisSummary(BaseModel):
    total_epochs: int
    valid_epochs: int
    fix_rate: float
    avg_confidence: float
    avg_heading_deg: Optional[float] = None
    avg_speed_knots: Optional[float] = None
    mean_position_error_m: Optional[float] = None
    max_position_error_m: Optional[float] = None
    model_usage: Dict[str, int]
    risk_distribution: Dict[str, int]
    retry_rounds: int
    dominant_strategy: str
    agent_sequence: List[str]
    key_findings: List[str]


class AnalysisResponse(BaseModel):
    dataset: DatasetInfo
    summary: AnalysisSummary
    epochs: List[EpochResult]
    explanation: str
    source_notes: List[str]
    agent_trace: List[AgentTrace]
    tool_sources: Dict[str, str]
    optional_context: Dict[str, Any] = Field(default_factory=dict)
    workflow: List[WorkflowStep] = Field(default_factory=list)
    protocol_log: List[ProtocolEvent] = Field(default_factory=list)


class MapConfigResponse(BaseModel):
    enabled: bool
    key: str = ""
    security_js_code: str = ""
    provider: str = "amap-jsapi"
    note: Optional[str] = None


class FollowupResponse(BaseModel):
    answer: str
    agent_trace: List[AgentTrace] = Field(default_factory=list)


class ScenarioStrategyConfig(BaseModel):
    recommended_mode: str
    candidate_count: int
    search_radius_deg: float
    temporal_hold_strength: float
    retry_thresholds: Dict[str, Any]
    enable_recovery_mode: bool
    selected_skills: List[str] = Field(default_factory=list)
    scene_tags: List[str] = Field(default_factory=list)
    rationale: str
    rationale_points: List[str] = Field(default_factory=list)
    collection_advice: List[str] = Field(default_factory=list)
    hotspot_references: List[str] = Field(default_factory=list)


class ScenarioPlanResponse(BaseModel):
    goal: str
    plan: ScenarioStrategyConfig
    agent_trace: List[AgentTrace] = Field(default_factory=list)
    historical_context: Dict[str, Any] = Field(default_factory=dict)
    protocol_log: List[ProtocolEvent] = Field(default_factory=list)


class StrategyCompareRequest(BaseModel):
    dataset_name: str = Field(default="google_mtv_local1")
    baseline_length_m: float = Field(default=1.20, ge=0.1, le=20.0)
    candidate_count: int = Field(default=5, ge=3, le=50)
    use_llm: bool = False
    enable_amap_geocode: bool = False
    strategy_names: List[str] = Field(default_factory=list)


class StrategyCompareItem(BaseModel):
    strategy_name: str
    display_name: str
    recommended_for: str
    parameters: Dict[str, Any]
    summary: AnalysisSummary
    score: float
    strengths: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)


class StrategyCompareResponse(BaseModel):
    dataset: DatasetInfo
    items: List[StrategyCompareItem]
    best_strategy: Optional[str] = None
    recommendation: str


class HotspotDiagnosisRequest(BaseModel):
    hotspot_id: str = Field(min_length=1, max_length=100)
    use_llm: bool = False


class HotspotDiagnosisResponse(BaseModel):
    hotspot_id: str
    title: str
    diagnosis: str
    evidence: Dict[str, Any]
    recommendations: List[str]
    suggested_strategy: Dict[str, Any]
    agent_trace: List[AgentTrace] = Field(default_factory=list)


class ExportReportRequest(BaseModel):
    format: str = Field(default="html", pattern="^(html|markdown)$")


class ExportReportResponse(BaseModel):
    filename: str
    mime_type: str
    content: str
    summary: Dict[str, Any] = Field(default_factory=dict)


class SampleEvaluationItem(BaseModel):
    dataset: DatasetInfo
    summary: AnalysisSummary
    hotspot_count: int
    recommended_scene_goal: str
    recommended_strategy: str
    demo_value: str


class SampleEvaluationResponse(BaseModel):
    items: List[SampleEvaluationItem]
    aggregate: Dict[str, Any]
