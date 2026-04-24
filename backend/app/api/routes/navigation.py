from __future__ import annotations

from pathlib import Path
import tempfile
from typing import List, Optional

from fastapi import APIRouter, File, Form, UploadFile

from app.agents.orchestrator import NavigationOrchestrator
from app.models.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    DatasetInfo,
    FollowupRequest,
    FollowupResponse,
    MapConfigResponse,
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
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_path = tmp_path / (file.filename or "uploaded.nmea")
        source_path.write_bytes(await file.read())
        reference_path = None
        if reference_file is not None:
            reference_path = tmp_path / (reference_file.filename or "reference.gga")
            reference_path.write_bytes(await reference_file.read())
        return service.analyze_file(
            file_path=source_path,
            dataset_name="uploaded_dataset",
            description="用户上传的 NMEA 数据集",
            baseline_length_m=baseline_length_m,
            candidate_count=candidate_count,
            use_llm=use_llm,
            enable_amap_geocode=enable_amap_geocode,
            reference_path=reference_path,
        )




@router.get("/map-config", response_model=MapConfigResponse)
def get_map_config() -> MapConfigResponse:
    return service.get_map_config()


@router.post("/followup", response_model=FollowupResponse)
def answer_followup(payload: FollowupRequest) -> FollowupResponse:
    return service.answer_followup(question=payload.question, use_llm=payload.use_llm)
