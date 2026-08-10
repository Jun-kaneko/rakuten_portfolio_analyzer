"""ポートフォリオ分析システム Web GUI のFastAPIアプリケーション本体。

起動方法:
    開発時: python -m uvicorn webapp.app:app --reload --host 127.0.0.1 --port 8000
    本番相当: python run.py（run.pyは webapp.app:app を同条件で起動する薄いラッパー）
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# portfolio_analyzer/ はパッケージ化されていないフラットなモジュール群のため、
# main.py 等と同じ analyzer / config / portfolio_loader / preferences /
# price_fetcher / news_fetcher をそのままimportできるよう、リポジトリルートを
# sys.path に追加する。main.py 自体はここから一切importしない
# （webapp/ → 既存トップレベルモジュール、の一方向依存を維持する）。
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.requests import Request  # noqa: E402

from config import ConfigError, load_config  # noqa: E402
from portfolio_loader import PortfolioLoadError  # noqa: E402
from preferences import PreferencesLoadError  # noqa: E402
from webapp import storage  # noqa: E402
from webapp.jobs import JobStore, create_executor  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        config = load_config()
    except ConfigError as exc:
        # main.py の「起動時に分かりやすく失敗する」方針を踏襲し、
        # APIキー未設定のままリクエストを受け付けることはしない。
        logger.error("設定の読み込みに失敗しました: %s", exc)
        raise
    if config.log_level:
        logging.getLogger().setLevel(config.log_level)

    storage.ensure_seed_data()

    app.state.config = config
    app.state.job_store = JobStore()
    app.state.executor = create_executor()
    logger.info("Web GUI バックエンドを起動しました（モデル: %s）", config.claude_model)
    try:
        yield
    finally:
        app.state.executor.shutdown(wait=False, cancel_futures=False)


app = FastAPI(title="ポートフォリオ分析システム Web GUI", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.exception_handler(PortfolioLoadError)
async def _handle_portfolio_load_error(request: Request, exc: PortfolioLoadError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(PreferencesLoadError)
async def _handle_preferences_load_error(request: Request, exc: PreferencesLoadError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(storage.StorageError)
async def _handle_storage_error(request: Request, exc: storage.StorageError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


from webapp.routers import analysis, portfolios, preferences, reports  # noqa: E402

app.include_router(portfolios.router)
app.include_router(preferences.router)
app.include_router(analysis.router)
app.include_router(reports.router)


# 本番運用時、フロントエンドのビルド成果物（webapp/frontend/dist）が
# 存在すればそれを配信する。存在しない場合（開発時、Vite dev serverを
# 別途使う場合）は何もマウントしない。APIルーター登録の後にマウントする
# ことで、/api/* が静的ファイル配信に奪われないようにする。
_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
