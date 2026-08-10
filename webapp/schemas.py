"""Web GUI APIのリクエスト/レスポンス用Pydanticモデル。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PortfolioFile(BaseModel):
    filename: str
    uploaded_at: str
    size_bytes: int


class PreferenceRecord(BaseModel):
    code: str
    name: str = ""
    affection_score: int = Field(ge=1, le=100)


class AnalyzeRequest(BaseModel):
    portfolio_filename: str
    preferences_filename: str | None = None
    cache_only: bool = False
    no_news: bool = False
    no_recommend: bool = False


class AnalyzeResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "succeeded", "failed"]


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "succeeded", "failed"]
    stage: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    report_id: str | None = None
    request: dict


class ReportSummary(BaseModel):
    report_id: str
    created_at: str
    portfolio_filename: str
    preferences_filename: str
    options: dict


class ReportDetail(ReportSummary):
    markdown: str
