"""ポートフォリオCSVの一覧取得・アップロードAPI。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile

from portfolio_loader import PortfolioLoadError, load_portfolio
from webapp import storage
from webapp.schemas import PortfolioFile

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


@router.get("", response_model=list[PortfolioFile])
def list_portfolios() -> list[dict]:
    return storage.list_portfolios()


@router.post("", response_model=PortfolioFile, status_code=201)
async def upload_portfolio(file: UploadFile) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空のファイルはアップロードできません。")

    saved_path = storage.save_uploaded_portfolio(file.filename or "portfolio.csv", content)
    try:
        # 保存直後にパース検証し、壊れたCSVが一覧に残らないようにする。
        load_portfolio(str(saved_path))
    except PortfolioLoadError:
        saved_path.unlink(missing_ok=True)
        raise

    stat = saved_path.stat()
    return {
        "filename": saved_path.name,
        "uploaded_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "size_bytes": stat.st_size,
    }
