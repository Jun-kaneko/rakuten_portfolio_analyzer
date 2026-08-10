"""Web GUI用の実行時データ（アップロードCSV・生成レポート）のパス管理。

保存先はすべて webapp/data/ 配下に集約し、個人の資産情報を含むため
.gitignore で除外する（webapp/data/ をまとめて除外）。愛着度設定
（stock_preferences.csv）だけはCLIと共有するためリポジトリ直下の
既存ファイルをそのまま使う。
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBAPP_DATA_DIR = Path(__file__).resolve().parent / "data"
PORTFOLIOS_DIR = WEBAPP_DATA_DIR / "portfolios"
REPORTS_DIR = WEBAPP_DATA_DIR / "reports"

# 愛着度設定はCLIと同じファイルを共有する（GUI専用の別ファイルは作らない）。
DEFAULT_PREFERENCES_PATH = REPO_ROOT / "stock_preferences.csv"

_SEED_PORTFOLIO = REPO_ROOT / "sample_portfolio.csv"

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-぀-ヿ一-鿿]")


class StorageError(Exception):
    """アップロードファイルの検証・保存に失敗した場合に送出する例外。"""


def ensure_dirs() -> None:
    """Web GUIが使う実行時データディレクトリを作成する（存在すれば何もしない）。"""
    PORTFOLIOS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_seed_data() -> None:
    """初回起動時、ポートフォリオ一覧が空ならサンプルCSVをコピーしておく。"""
    ensure_dirs()
    if any(PORTFOLIOS_DIR.glob("*.csv")):
        return
    if _SEED_PORTFOLIO.exists():
        shutil.copy(_SEED_PORTFOLIO, PORTFOLIOS_DIR / _SEED_PORTFOLIO.name)


def sanitize_filename(original_name: str) -> str:
    """アップロードファイル名を安全な形式に正規化する（パストラバーサル対策込み）。

    Args:
        original_name: クライアントが送ってきた元のファイル名。

    Returns:
        str: 英数字・日本語・`-_.`のみで構成された安全なファイル名（拡張子は`.csv`固定）。

    Raises:
        StorageError: 拡張子が`.csv`でない、またはサニタイズ後の名前が空の場合。
    """
    name = Path(original_name).name  # ディレクトリ部分を除去
    if not name.lower().endswith(".csv"):
        raise StorageError("CSVファイル（拡張子.csv）のみアップロードできます。")
    stem = name[: -len(".csv")]
    safe_stem = _SAFE_NAME_RE.sub("_", stem).strip("_") or "portfolio"
    return f"{safe_stem}.csv"


def save_uploaded_portfolio(original_name: str, content: bytes) -> Path:
    """アップロードされたポートフォリオCSVを保存し、保存先パスを返す。

    ファイル名は `<timestamp>_<sanitized_original_name>` とし、
    衝突回避とアップロード順の一覧表示を両立させる。
    """
    ensure_dirs()
    safe_name = sanitize_filename(original_name)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = PORTFOLIOS_DIR / f"{timestamp}_{safe_name}"
    dest.write_bytes(content)
    return dest


def resolve_portfolio_path(filename: str) -> Path:
    """ポートフォリオファイル名からwebapp/data/portfolios配下の絶対パスを解決する。

    Raises:
        StorageError: filenameがportfolios配下から逸脱する、またはファイルが存在しない場合。
    """
    ensure_dirs()
    candidate = (PORTFOLIOS_DIR / Path(filename).name).resolve()
    if PORTFOLIOS_DIR.resolve() not in candidate.parents:
        raise StorageError(f"不正なポートフォリオファイル名です: {filename}")
    if not candidate.exists():
        raise StorageError(f"ポートフォリオファイルが見つかりません: {filename}")
    return candidate


def list_portfolios() -> list[dict]:
    """アップロード済みポートフォリオCSVの一覧を更新日時の新しい順で返す。"""
    ensure_seed_data()
    entries = []
    for path in PORTFOLIOS_DIR.glob("*.csv"):
        stat = path.stat()
        entries.append(
            {
                "filename": path.name,
                "uploaded_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "size_bytes": stat.st_size,
            }
        )
    entries.sort(key=lambda e: e["uploaded_at"], reverse=True)
    return entries


@dataclass
class ReportRecord:
    report_id: str
    created_at: str
    portfolio_filename: str
    preferences_filename: str
    options: dict


def new_report_id() -> str:
    """タイムスタンプ＋短いランダムサフィックスで衝突しにくいreport_idを生成する。"""
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def report_markdown_path(report_id: str) -> Path:
    return REPORTS_DIR / f"{report_id}.md"


def report_meta_path(report_id: str) -> Path:
    return REPORTS_DIR / f"{report_id}.meta.json"


def save_report_meta(record: ReportRecord) -> None:
    ensure_dirs()
    report_meta_path(record.report_id).write_text(
        json.dumps(
            {
                "report_id": record.report_id,
                "created_at": record.created_at,
                "portfolio_filename": record.portfolio_filename,
                "preferences_filename": record.preferences_filename,
                "options": record.options,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def list_reports() -> list[dict]:
    """生成済みレポートのメタデータ一覧を新しい順で返す。"""
    ensure_dirs()
    records = []
    for meta_path in REPORTS_DIR.glob("*.meta.json"):
        try:
            records.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return records


def read_report(report_id: str) -> dict | None:
    """指定report_idのMarkdown本文とメタデータをまとめて返す（無ければNone）。"""
    md_path = report_markdown_path(report_id)
    meta_path = report_meta_path(report_id)
    if not md_path.exists():
        return None
    markdown = md_path.read_text(encoding="utf-8")
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    return {"report_id": report_id, "markdown": markdown, **meta}
