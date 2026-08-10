"""バックグラウンドジョブ機構（インメモリジョブストア＋ThreadPoolExecutor）。

analyze_portfolio() / recommend_stocks() はClaude API呼び出しのため
数十秒〜数分かかり、同期HTTPリクエストで待たせることはできない。
POST /api/analyze はジョブを作成しExecutorへ投入したうえで即座に
job_idを返し、フロントエンドは GET /api/jobs/{id} を定期的にポーリングして
進捗（stage）と結果を確認する。

ワーカー数は1に固定する。ローカル単一ユーザーツールであり同時実行の
必要性がなく、2件目以降のリクエストは自然にキューイングされる
（Claude APIのレート制限・二重課金対策にもなる）。

ジョブの状態はインメモリのみで、サーバー再起動で失われる。生成された
レポート自体はファイル＋メタJSON（storage.py）として永続化されるため、
「履歴」としての実害は小さい。
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

import pandas as pd

from analyzer import AnalysisError, analyze_portfolio, build_metrics, recommend_stocks, save_report
from config import Config
from news_fetcher import fetch_news_for_portfolio
from portfolio_loader import PortfolioLoadError, load_portfolio
from preferences import PreferencesLoadError, load_preferences
from price_fetcher import fetch_prices_for_portfolio
from webapp import storage

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class Job:
    job_id: str
    status: JobStatus
    request: dict
    stage: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    report_id: str | None = None

    def to_response(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "started_at": self.started_at.isoformat(timespec="seconds") if self.started_at else None,
            "finished_at": self.finished_at.isoformat(timespec="seconds") if self.finished_at else None,
            "error": self.error,
            "report_id": self.report_id,
            "request": self.request,
        }


class JobStore:
    """ジョブの作成・更新・取得をスレッドセーフに行うインメモリストア。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def create(self, job_id: str, request: dict) -> Job:
        job = Job(job_id=job_id, status="pending", request=request)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                logger.warning("未知のjob_idへの更新を無視しました: %s", job_id)
                return
            self._jobs[job_id] = replace(current, **fields)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


def create_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis-job")


def submit_analysis_job(
    executor: ThreadPoolExecutor,
    job_store: JobStore,
    config: Config,
    job_id: str,
    params: dict,
) -> None:
    """分析ジョブをExecutorへ投入する（呼び出し元は即座に制御を戻す）。"""
    executor.submit(_run_analysis_job, job_store, config, job_id, params)


def _run_analysis_job(job_store: JobStore, config: Config, job_id: str, params: dict) -> None:
    """main.py の処理順序をなぞりつつ、各ステップの直前にstageを更新する。

    main.py の main() 関数と同じ例外方針を踏襲する:
    - PortfolioLoadError / PreferencesLoadError は即座に失敗として扱う
    - ニュース取得の失敗は警告のみで継続（分析自体は続ける）
    - AnalysisError（analyze_portfolio）は失敗確定
    - おすすめ銘柄提案（recommend_stocks）の失敗は警告のみで継続し、
      分析結果自体は保存する
    """
    job_store.update(job_id, status="running", started_at=datetime.now(), stage="ポートフォリオ読み込み中")

    portfolio_filename = params["portfolio_filename"]
    preferences_filename = params.get("preferences_filename") or storage.DEFAULT_PREFERENCES_PATH.name
    cache_only = bool(params.get("cache_only"))
    no_news = bool(params.get("no_news"))
    no_recommend = bool(params.get("no_recommend"))

    try:
        portfolio_path = storage.resolve_portfolio_path(portfolio_filename)
    except storage.StorageError as exc:
        job_store.update(job_id, status="failed", finished_at=datetime.now(), error=str(exc))
        return

    try:
        df: pd.DataFrame = load_portfolio(str(portfolio_path))
    except PortfolioLoadError as exc:
        logger.error("ポートフォリオCSVの読み込みに失敗しました: %s", exc)
        job_store.update(job_id, status="failed", finished_at=datetime.now(), error=str(exc))
        return

    job_store.update(job_id, stage="株価取得中")
    try:
        prices = fetch_prices_for_portfolio(df, config, cache_only=cache_only)
    except Exception as exc:  # noqa: BLE001 - main.py と同じく想定外エラーも捕捉して失敗にする
        logger.error("株価取得処理で予期しないエラーが発生しました: %s", exc, exc_info=True)
        job_store.update(job_id, status="failed", finished_at=datetime.now(), error=str(exc))
        return

    news: dict[str, list[dict]] = {}
    if no_news:
        logger.info("no_news が指定されたため、ニュース取得をスキップします")
    else:
        job_store.update(job_id, stage="ニュース取得中")
        try:
            news = fetch_news_for_portfolio(df, config, cache_only=cache_only)
        except Exception as exc:  # noqa: BLE001 - ニュース取得の失敗で分析全体は止めない
            logger.warning("ニュース取得処理で予期しないエラーが発生しました（分析は継続します）: %s", exc, exc_info=True)

    job_store.update(job_id, stage="愛着度設定読み込み中")
    try:
        preferences = load_preferences(str(storage.DEFAULT_PREFERENCES_PATH))
    except PreferencesLoadError as exc:
        logger.error("愛着度設定CSVの読み込みに失敗しました: %s", exc)
        job_store.update(job_id, status="failed", finished_at=datetime.now(), error=str(exc))
        return

    job_store.update(job_id, stage="指標計算中")
    metrics = build_metrics(df, prices, preferences)

    job_store.update(job_id, stage="Claude分析中")
    try:
        report_markdown = analyze_portfolio(metrics, config, news)
    except AnalysisError as exc:
        logger.error("Claude APIによる分析に失敗しました: %s", exc)
        job_store.update(job_id, status="failed", finished_at=datetime.now(), error=str(exc))
        return

    if no_recommend:
        logger.info("no_recommend が指定されたため、おすすめ銘柄の提案をスキップします")
    elif cache_only:
        logger.info("cache_only が指定されているため、web検索を伴うおすすめ銘柄の提案をスキップします")
    else:
        job_store.update(job_id, stage="おすすめ銘柄提案中")
        try:
            recommendation_markdown = recommend_stocks(metrics, config)
            report_markdown = report_markdown + "\n\n---\n\n" + recommendation_markdown
        except AnalysisError as exc:
            logger.warning("おすすめ銘柄の提案生成に失敗しました（分析結果は保存を継続します）: %s", exc)

    job_store.update(job_id, stage="レポート保存中")
    report_id = storage.new_report_id()
    report_path = storage.report_markdown_path(report_id)
    save_report(report_markdown, str(report_path))
    storage.save_report_meta(
        storage.ReportRecord(
            report_id=report_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            portfolio_filename=portfolio_filename,
            preferences_filename=preferences_filename,
            options={"cache_only": cache_only, "no_news": no_news, "no_recommend": no_recommend},
        )
    )

    job_store.update(
        job_id,
        status="succeeded",
        finished_at=datetime.now(),
        stage="完了",
        report_id=report_id,
    )
