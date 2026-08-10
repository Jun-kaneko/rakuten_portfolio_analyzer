"""分析ジョブの起動・進捗確認API。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from webapp.jobs import submit_analysis_job
from webapp.schemas import AnalyzeRequest, AnalyzeResponse, JobStatusResponse

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/analyze", response_model=AnalyzeResponse, status_code=202)
def start_analysis(payload: AnalyzeRequest, request: Request) -> dict:
    job_id = uuid.uuid4().hex
    params = payload.model_dump()
    request.app.state.job_store.create(job_id, params)
    submit_analysis_job(
        request.app.state.executor,
        request.app.state.job_store,
        request.app.state.config,
        job_id,
        params,
    )
    return {"job_id": job_id, "status": "pending"}


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, request: Request) -> dict:
    job = request.app.state.job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"ジョブが見つかりません: {job_id}")
    return job.to_response()
