"""愛着度設定（stock_preferences.csv）の取得・編集保存API。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from portfolio_loader import load_portfolio
from preferences import DEFAULT_SCORE, load_preferences_records, save_preferences
from webapp import storage
from webapp.schemas import PreferenceRecord

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("", response_model=list[PreferenceRecord])
def get_preferences(portfolio: str | None = Query(default=None)) -> list[dict]:
    records = load_preferences_records(str(storage.DEFAULT_PREFERENCES_PATH))
    if not portfolio:
        return records

    known_codes = {r["code"] for r in records}
    try:
        portfolio_path = storage.resolve_portfolio_path(portfolio)
        df = load_portfolio(str(portfolio_path))
    except Exception:  # noqa: BLE001 - ポートフォリオ側の読み込み失敗時は愛着度設定のみ返す
        # （GUI側で選択中ポートフォリオが未確定の場合など、ここでは失敗させない）。
        return records

    for _, row in df.drop_duplicates(subset="code").iterrows():
        code = row["code"]
        if code not in known_codes:
            records.append({"code": code, "name": row.get("name", ""), "affection_score": DEFAULT_SCORE})
            known_codes.add(code)

    return records


@router.put("", response_model=list[PreferenceRecord])
def put_preferences(records: list[PreferenceRecord]) -> list[dict]:
    payload = [r.model_dump() for r in records]
    save_preferences(payload, str(storage.DEFAULT_PREFERENCES_PATH))
    return load_preferences_records(str(storage.DEFAULT_PREFERENCES_PATH))
