"""ジョブ機構（webapp/jobs.py）のユニットテスト。

analyze_portfolio()/recommend_stocks() はClaude API呼び出しのため課金が
発生する。反復検証のコストを避けるため、このテストでは両関数を常に
mockし、実際のAPI呼び出しを一切行わない。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from webapp import jobs, storage

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """storage.py のデータディレクトリをテスト用の一時ディレクトリへ差し替える。"""
    portfolios_dir = tmp_path / "portfolios"
    reports_dir = tmp_path / "reports"
    portfolios_dir.mkdir()
    reports_dir.mkdir()
    preferences_path = tmp_path / "stock_preferences.csv"

    monkeypatch.setattr(storage, "PORTFOLIOS_DIR", portfolios_dir)
    monkeypatch.setattr(storage, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(storage, "DEFAULT_PREFERENCES_PATH", preferences_path)

    # sample_portfolio.csv を一時ディレクトリへコピーして選択肢として使う。
    shutil.copy(REPO_ROOT / "sample_portfolio.csv", portfolios_dir / "sample_portfolio.csv")
    return tmp_path


@pytest.fixture
def dummy_config():
    from config import Config

    return Config(anthropic_api_key="dummy-key-for-tests")


def _wait_until_done(job_store: jobs.JobStore, job_id: str, timeout: float = 5.0) -> jobs.Job:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = job_store.get(job_id)
        if job.status in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"ジョブが時間内に完了しませんでした: {job.status if job else None}")


def test_run_analysis_job_succeeds_with_mocked_claude(isolated_storage, dummy_config):
    """正常系: analyzer.*をmockした状態でジョブがsucceededになり、レポートが保存されること。

    recommend_stocks が実際に呼ばれる経路を検証するため cache_only=False
    にする（cache_only=True は main.py と同じ理由でおすすめ提案を強制
    スキップする仕様であり、それは別テストで検証する）。fetch_prices_for_
    portfolio はネットワークI/O・リトライを伴うため、実ネットワークに
    依存しないようこちらもmockする。
    """
    job_store = jobs.JobStore()
    job_id = "test-job-1"
    params = {
        "portfolio_filename": "sample_portfolio.csv",
        "cache_only": False,
        "no_news": True,
        "no_recommend": False,
    }
    job_store.create(job_id, params)

    with patch("webapp.jobs.fetch_prices_for_portfolio", return_value={}), \
         patch("webapp.jobs.analyze_portfolio", return_value="## ダミー分析結果") as mock_analyze, \
         patch("webapp.jobs.recommend_stocks", return_value="## ダミーおすすめ銘柄") as mock_recommend:
        jobs._run_analysis_job(job_store, dummy_config, job_id, params)

    job = job_store.get(job_id)
    assert job.status == "succeeded"
    assert job.report_id is not None
    assert job.stage == "完了"
    mock_analyze.assert_called_once()
    mock_recommend.assert_called_once()

    report = storage.read_report(job.report_id)
    assert report is not None
    assert "ダミー分析結果" in report["markdown"]
    assert "ダミーおすすめ銘柄" in report["markdown"]


def test_run_analysis_job_skips_recommend_when_cache_only(isolated_storage, dummy_config):
    """cache_only=True の場合、no_recommendがFalseでもおすすめ銘柄提案はスキップされること
    （main.py の分岐ロジックと同じ挙動）。"""
    job_store = jobs.JobStore()
    job_id = "test-job-2"
    params = {
        "portfolio_filename": "sample_portfolio.csv",
        "cache_only": True,
        "no_news": True,
        "no_recommend": False,
    }
    job_store.create(job_id, params)

    with patch("webapp.jobs.analyze_portfolio", return_value="## ダミー分析結果") as mock_analyze, \
         patch("webapp.jobs.recommend_stocks") as mock_recommend:
        jobs._run_analysis_job(job_store, dummy_config, job_id, params)

    job = job_store.get(job_id)
    assert job.status == "succeeded"
    mock_analyze.assert_called_once()
    mock_recommend.assert_not_called()


def test_run_analysis_job_fails_for_unknown_portfolio(isolated_storage, dummy_config):
    """存在しないポートフォリオファイルを指定した場合、Claude APIを呼ばずに失敗すること。"""
    job_store = jobs.JobStore()
    job_id = "test-job-3"
    params = {"portfolio_filename": "does-not-exist.csv"}
    job_store.create(job_id, params)

    with patch("webapp.jobs.analyze_portfolio") as mock_analyze:
        jobs._run_analysis_job(job_store, dummy_config, job_id, params)

    job = job_store.get(job_id)
    assert job.status == "failed"
    assert job.error is not None
    mock_analyze.assert_not_called()


def test_run_analysis_job_continues_when_recommend_fails(isolated_storage, dummy_config):
    """おすすめ銘柄提案が失敗しても、分析結果自体は保存されジョブはsucceededになること。"""
    from analyzer import AnalysisError

    job_store = jobs.JobStore()
    job_id = "test-job-4"
    params = {
        "portfolio_filename": "sample_portfolio.csv",
        "cache_only": True,
        "no_news": True,
        "no_recommend": False,
    }
    job_store.create(job_id, params)

    with patch("webapp.jobs.analyze_portfolio", return_value="## ダミー分析結果"), \
         patch("webapp.jobs.recommend_stocks", side_effect=AnalysisError("dummy failure")):
        jobs._run_analysis_job(job_store, dummy_config, job_id, params)

    job = job_store.get(job_id)
    assert job.status == "succeeded"
    report = storage.read_report(job.report_id)
    assert "ダミー分析結果" in report["markdown"]
    assert "ダミーおすすめ" not in report["markdown"]


def test_submit_analysis_job_via_executor(isolated_storage, dummy_config):
    """submit_analysis_job()経由（ThreadPoolExecutor実行）でも同様に完了すること。"""
    job_store = jobs.JobStore()
    executor = jobs.create_executor()
    job_id = "test-job-5"
    params = {
        "portfolio_filename": "sample_portfolio.csv",
        "cache_only": True,
        "no_news": True,
        "no_recommend": True,
    }
    job_store.create(job_id, params)

    try:
        with patch("webapp.jobs.analyze_portfolio", return_value="## ダミー分析結果"):
            jobs.submit_analysis_job(executor, job_store, dummy_config, job_id, params)
            job = _wait_until_done(job_store, job_id)
    finally:
        executor.shutdown(wait=True)

    assert job.status == "succeeded"
