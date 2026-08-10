"""銘柄ごとの「愛着度」設定を読み込むモジュール。

投資判断は損益やPER/PBRだけでなく、以下のような個人的な方針にも左右される。

1. 好きな銘柄は基本売らない（追加購入はありうる）
2. 長く保有していて嫌いではない銘柄は売却を検討しうるが、タイミングの判断が難しい

これらのうち「1.（銘柄への愛着）」を 1〜100 のスコアとして明示的に設定できるように
し、Claude APIへの分析プロンプトに組み込むことで、AIの提案が個人の方針を踏まえた
ものになるようにする。

CSV形式（code, affection_score が必須。name は銘柄コードだけでは分かりにくい
ため人間が読みやすくする目的の任意カラムで、値自体は分析には使用しない）:
    code,name,affection_score
    9983,良品計画,90
    7203,トヨタ自動車,85
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["code", "affection_score"]

DEFAULT_SCORE = 50
MIN_SCORE = 1
MAX_SCORE = 100


class PreferencesLoadError(Exception):
    """愛着度設定CSVの読み込み・検証に失敗した場合に送出する例外。"""


def load_preferences(csv_path: str) -> dict[str, int]:
    """愛着度設定CSVを読み込み、銘柄コード→スコア（1〜100）の辞書を返す。

    ファイルが存在しない場合はエラーにせず空の辞書を返す（呼び出し側で
    DEFAULT_SCORE を適用する）。愛着度設定はあくまで任意の補助情報であり、
    未設定でも分析自体は継続できるべきだからである。

    Args:
        csv_path: 愛着度設定CSVファイルパス（code, affection_score が必須。
            name列は可読性のための任意カラムで、あってもなくても読み込める）。

    Returns:
        dict[str, int]: 銘柄コードをキーとした愛着度スコア（1〜100）。
            ファイルが存在しない・空の場合は空の辞書。

    Raises:
        PreferencesLoadError: ファイルは存在するが必須カラムが欠落している、
            またはスコアが数値変換できない・範囲外（1〜100）の場合。
    """
    path = Path(csv_path)
    if not path.exists():
        logger.warning(
            "愛着度設定CSVが見つかりません（%s）。全銘柄をデフォルト値%dとして扱います。",
            csv_path,
            DEFAULT_SCORE,
        )
        return {}

    try:
        df = pd.read_csv(path, dtype={"code": str})
    except pd.errors.EmptyDataError:
        logger.warning(
            "愛着度設定CSVが空です（%s）。全銘柄をデフォルト値%dとして扱います。",
            csv_path,
            DEFAULT_SCORE,
        )
        return {}
    except pd.errors.ParserError as exc:
        raise PreferencesLoadError(
            f"愛着度設定CSVの形式が不正です: {csv_path} ({exc})"
        ) from exc

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        raise PreferencesLoadError(
            f"愛着度設定CSVに必須カラムがありません: {', '.join(missing_columns)}\n"
            f"必須カラム: {', '.join(REQUIRED_COLUMNS)}"
        )

    df["code"] = df["code"].str.strip()
    df["affection_score"] = pd.to_numeric(df["affection_score"], errors="coerce")

    invalid = df[
        df["affection_score"].isna()
        | (df["affection_score"] < MIN_SCORE)
        | (df["affection_score"] > MAX_SCORE)
    ]
    if not invalid.empty:
        raise PreferencesLoadError(
            f"愛着度スコアは{MIN_SCORE}〜{MAX_SCORE}の数値で指定してください。"
            f"不正な行の銘柄コード: {', '.join(invalid['code'].fillna('(不明)'))}"
        )

    preferences = dict(zip(df["code"], df["affection_score"].astype(int)))
    logger.info("愛着度設定を読み込みました: %d銘柄 (%s)", len(preferences), csv_path)
    return preferences


def load_preferences_records(csv_path: str) -> list[dict]:
    """愛着度設定CSVを、GUIでの表示・編集用にレコードのリストとして返す。

    load_preferences() は分析処理で使う {code: score} の辞書のみを返し
    name列を保持しないため、Web GUIでの表示・編集・保存の往復に使う
    このヘルパーを別途用意する。バリデーション（必須カラム・スコア範囲）は
    load_preferences() と同じ規則に従う。

    Args:
        csv_path: 愛着度設定CSVファイルパス。

    Returns:
        list[dict]: [{"code": str, "name": str, "affection_score": int}, ...]。
            ファイルが存在しない・空の場合は空リスト。name列が無いCSVの場合、
            nameは空文字になる。

    Raises:
        PreferencesLoadError: load_preferences() と同じ条件で送出される。
    """
    path = Path(csv_path)
    if not path.exists():
        return []

    try:
        df = pd.read_csv(path, dtype={"code": str})
    except pd.errors.EmptyDataError:
        return []
    except pd.errors.ParserError as exc:
        raise PreferencesLoadError(
            f"愛着度設定CSVの形式が不正です: {csv_path} ({exc})"
        ) from exc

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        raise PreferencesLoadError(
            f"愛着度設定CSVに必須カラムがありません: {', '.join(missing_columns)}\n"
            f"必須カラム: {', '.join(REQUIRED_COLUMNS)}"
        )

    df["code"] = df["code"].str.strip()
    df["affection_score"] = pd.to_numeric(df["affection_score"], errors="coerce")

    invalid = df[
        df["affection_score"].isna()
        | (df["affection_score"] < MIN_SCORE)
        | (df["affection_score"] > MAX_SCORE)
    ]
    if not invalid.empty:
        raise PreferencesLoadError(
            f"愛着度スコアは{MIN_SCORE}〜{MAX_SCORE}の数値で指定してください。"
            f"不正な行の銘柄コード: {', '.join(invalid['code'].fillna('(不明)'))}"
        )

    if "name" not in df.columns:
        df["name"] = ""
    df["name"] = df["name"].fillna("")

    return [
        {"code": row["code"], "name": row["name"], "affection_score": int(row["affection_score"])}
        for _, row in df.iterrows()
    ]


def save_preferences(records: list[dict], csv_path: str) -> None:
    """愛着度設定レコードを検証してCSVに書き込む。

    Web GUIでの編集内容を stock_preferences.csv （またはそれに相当する
    パス）へ永続化するために使う。CLI側の load_preferences() の想定する
    フォーマット（code, name, affection_score）と完全に互換性を保つ。

    Args:
        records: [{"code": str, "name": str, "affection_score": int}, ...]。
        csv_path: 書き込み先CSVファイルパス。

    Raises:
        PreferencesLoadError: codeが空、またはaffection_scoreが
            MIN_SCORE〜MAX_SCOREの範囲外の場合。
    """
    invalid_codes = []
    normalized: list[dict] = []
    for record in records:
        code = str(record.get("code", "")).strip()
        name = str(record.get("name", "") or "")
        score = record.get("affection_score")
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = None
        if not code or score is None or score < MIN_SCORE or score > MAX_SCORE:
            invalid_codes.append(code or "(不明)")
            continue
        normalized.append({"code": code, "name": name, "affection_score": score})

    if invalid_codes:
        raise PreferencesLoadError(
            f"愛着度スコアは{MIN_SCORE}〜{MAX_SCORE}の数値で指定してください。"
            f"不正な行の銘柄コード: {', '.join(invalid_codes)}"
        )

    df = pd.DataFrame(normalized, columns=["code", "name", "affection_score"])
    df.to_csv(csv_path, index=False)
    logger.info("愛着度設定を保存しました: %d銘柄 (%s)", len(normalized), csv_path)
