"""生成済みレポートの履歴一覧・個別取得API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from webapp import storage
from webapp.schemas import ReportDetail, ReportSummary

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=list[ReportSummary])
def list_reports() -> list[dict]:
    return storage.list_reports()


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(report_id: str) -> dict:
    report = storage.read_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"レポートが見つかりません: {report_id}")
    return report
