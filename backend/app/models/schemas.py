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




class MapConfigResponse(BaseModel):
    enabled: bool
    key: str = ""
    security_js_code: str = ""
    provider: str = "amap-jsapi"
    note: Optional[str] = None


class FollowupResponse(BaseModel):
    answer: str
    agent_trace: List[AgentTrace] = Field(default_factory=list)
