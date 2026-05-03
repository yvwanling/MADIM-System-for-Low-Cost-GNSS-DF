from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agents.orchestrator import NavigationOrchestrator
from app.models.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    DatasetInfo,
    FollowupRequest,
    FollowupResponse,
    MapConfigResponse,
    ScenarioPlanRequest,
    ScenarioPlanResponse,
    StrategyCompareRequest,
    StrategyCompareResponse,
    HotspotDiagnosisRequest,
    HotspotDiagnosisResponse,
    ExportReportRequest,
    ExportReportResponse,
    SampleEvaluationResponse,
)


router = APIRouter(prefix="/api/navigation", tags=["navigation"])
service = NavigationOrchestrator()


@router.get("/datasets", response_model=List[DatasetInfo])
def list_datasets() -> List[DatasetInfo]:
    return service.list_datasets()


@router.post("/analyze-sample", response_model=AnalysisResponse)
def analyze_sample(payload: AnalysisRequest) -> AnalysisResponse:
    return service.analyze_dataset(
        dataset_name=payload.dataset_name,
        baseline_length_m=payload.baseline_length_m,
        candidate_count=payload.candidate_count,
        use_llm=payload.use_llm,
        enable_amap_geocode=payload.enable_amap_geocode,
    )


@router.post("/upload-nmea", response_model=AnalysisResponse)
async def analyze_uploaded_nmea(
    file: UploadFile = File(...),
    reference_file: Optional[UploadFile] = File(default=None),
    baseline_length_m: float = Form(1.20),
    candidate_count: int = Form(5),
    use_llm: bool = Form(False),
    enable_amap_geocode: bool = Form(False),
) -> AnalysisResponse:
    """Upload, persist, auto-register, then analyze an NMEA dataset.

    The uploaded file is saved under data/raw/uploads and written into
    data/raw/uploaded_datasets.json. It can immediately participate in the
    dataset evaluation panel and strategy comparison without manual copying.
    """
    try:
        file_bytes = await file.read()
        reference_bytes = await reference_file.read() if reference_file is not None else None
        dataset_name, _item = service.register_uploaded_dataset(
            file_bytes=file_bytes,
            filename=file.filename,
            reference_bytes=reference_bytes,
            reference_filename=reference_file.filename if reference_file is not None else None,
            description=f"用户上传的数据集：{file.filename or 'uploaded.nmea'}。可直接参与数据集评测和多策略对比。",
        )
        return service.analyze_dataset(
            dataset_name=dataset_name,
            baseline_length_m=baseline_length_m,
            candidate_count=candidate_count,
            use_llm=use_llm,
            enable_amap_geocode=enable_amap_geocode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/map-config", response_model=MapConfigResponse)
def get_map_config() -> MapConfigResponse:
    return service.get_map_config()


@router.post("/followup", response_model=FollowupResponse)
def answer_followup(payload: FollowupRequest) -> FollowupResponse:
    return service.answer_followup(question=payload.question, use_llm=payload.use_llm)


@router.post("/plan-scenario", response_model=ScenarioPlanResponse)
def plan_scenario(payload: ScenarioPlanRequest) -> ScenarioPlanResponse:
    return service.plan_scenario_strategy(goal=payload.goal, use_llm=payload.use_llm)


@router.post("/compare-strategies", response_model=StrategyCompareResponse)
def compare_strategies(payload: StrategyCompareRequest) -> StrategyCompareResponse:
    return service.compare_strategies(
        dataset_name=payload.dataset_name,
        baseline_length_m=payload.baseline_length_m,
        candidate_count=payload.candidate_count,
        use_llm=payload.use_llm,
        enable_amap_geocode=payload.enable_amap_geocode,
        strategy_names=payload.strategy_names,
    )


@router.post("/diagnose-hotspot", response_model=HotspotDiagnosisResponse)
def diagnose_hotspot(payload: HotspotDiagnosisRequest) -> HotspotDiagnosisResponse:
    return service.diagnose_hotspot(hotspot_id=payload.hotspot_id, use_llm=payload.use_llm)


@router.post("/export-report", response_model=ExportReportResponse)
def export_report(payload: ExportReportRequest) -> ExportReportResponse:
    return service.export_report(fmt=payload.format)


@router.post("/evaluate-samples", response_model=SampleEvaluationResponse)
def evaluate_samples(payload: AnalysisRequest | None = None) -> SampleEvaluationResponse:
    baseline_length_m = payload.baseline_length_m if payload else 1.20
    candidate_count = payload.candidate_count if payload else 5
    return service.evaluate_samples(baseline_length_m=baseline_length_m, candidate_count=candidate_count)
