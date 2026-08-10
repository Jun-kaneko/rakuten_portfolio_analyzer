"""保有銘柄CSVを読み込むモジュール。

3つの形式に対応する。

1. シンプル形式（テスト・サンプル用）
   カラム: code, name, purchase_price, quantity, purchase_date
   UTF-8エンコーディングの単一テーブルCSV。

2. 楽天証券「資産残高」エクスポート形式（assetbalance_*.csv）
   Shift-JIS(CP932)エンコーディングで、■特定口座・■NISA成長投資枠 等の
   複数セクションから成る帳票形式のCSV。銘柄コード・銘柄名・保有数量・
   平均取得価額列を各セクションから抽出する。購入日（purchase_date）は
   この形式には含まれないため NaT（欠損）として扱う。

3. 楽天証券「取引履歴」エクスポート形式（tradehistory*.csv）
   Shift-JIS(CP932)エンコーディングで、約定日ごとの買付・売付・入庫/出庫の
   明細が並ぶ形式。現在の保有銘柄そのものは含まれないため、口座区分・銘柄
   コードごとに時系列で数量と取得総額を集計（移動平均法）し、現在保有中
   （数量>0）の銘柄のみを抽出する。入庫/出庫は株式分割等による数量調整で
   あることが多く、取得総額は据え置いて数量のみ増減させる（詳細は
   `_parse_trade_history_format` のdocstring参照）。この集計方法により
   算出した取得単価は、実際の資産残高CSVの値とほぼ一致することを確認済み
   だが、口座間移管等で真にコストが発生する入庫があった場合は誤差が生じ
   うる。購入日（purchase_date）は、保有数量が0から増加した直近の約定日
   （＝現在のポジションを開始した日）を推定値として設定する。

いずれの形式かはファイル内容から自動判別する。
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["code", "name", "purchase_price", "quantity", "purchase_date"]

# 楽天証券「資産残高」CSVのセクション見出し・列ラベル
_SECTION_MARKER_PREFIX = "■"
_CODE_LABEL = "銘柄コード"
_NAME_LABEL = "銘柄名"
_QUANTITY_LABEL = "保有数量［株］"
_PRICE_LABEL = "平均取得価額［円］"

# 楽天証券「取引履歴」CSVの列ラベル
_TRADE_DATE_LABEL = "約定日"
_TRADE_ACCOUNT_LABEL = "口座区分"
_TRADE_SIDE_LABEL = "売買区分"
_TRADE_MARGIN_LABEL = "信用区分"
_TRADE_QUANTITY_LABEL = "数量［株］"
_TRADE_PRICE_LABEL = "単価［円］"
_TRADE_SETTLEMENT_LABEL = "受渡金額［円］"
_TRADE_REQUIRED_LABELS = [
    _TRADE_DATE_LABEL,
    _CODE_LABEL,
    _NAME_LABEL,
    _TRADE_ACCOUNT_LABEL,
    _TRADE_SIDE_LABEL,
    _TRADE_QUANTITY_LABEL,
    _TRADE_PRICE_LABEL,
]
# 口座区分の表記を資産残高CSV側（例: 特定口座）と揃えるための対応表
_ACCOUNT_LABEL_ALIASES = {"特定": "特定口座", "一般": "一般口座"}

# 文字コード自動判別で試すエンコーディング（優先順）
_CANDIDATE_ENCODINGS = ("utf-8-sig", "cp932")


class PortfolioLoadError(Exception):
    """保有銘柄CSVの読み込み・検証に失敗した場合に送出する例外。"""


def _read_text(path: Path) -> str:
    """CSVファイルをUTF-8/Shift-JIS(CP932)のいずれかとして読み込む。"""
    raw = path.read_bytes()
    for encoding in _CANDIDATE_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PortfolioLoadError(
        f"CSVの文字コードを判別できませんでした（UTF-8/Shift-JISのいずれでもデコード失敗）: {path}"
    )


def _looks_like_simple_format(text: str) -> bool:
    """1行目がシンプル形式（英語カラム名）のヘッダかどうかを判定する。"""
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    header_cells = [cell.strip().strip('"') for cell in first_line.split(",")]
    return "code" in header_cells and "purchase_price" in header_cells


def _looks_like_trade_history_format(text: str) -> bool:
    """1行目が取引履歴形式（約定日を含むヘッダ）かどうかを判定する。"""
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    header_cells = [cell.strip().strip('"') for cell in first_line.split(",")]
    return _TRADE_DATE_LABEL in header_cells and _CODE_LABEL in header_cells


def _parse_simple_format(text: str) -> pd.DataFrame:
    """シンプル形式（code, name, purchase_price, quantity, purchase_date）を読み込む。"""
    try:
        # 銘柄コードの先頭ゼロ落ちを防ぐため code は文字列として読み込む
        df = pd.read_csv(io.StringIO(text), dtype={"code": str})
    except pd.errors.EmptyDataError as exc:
        raise PortfolioLoadError("CSVファイルが空です") from exc
    except pd.errors.ParserError as exc:
        raise PortfolioLoadError(f"CSVの形式が不正です ({exc})") from exc

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        raise PortfolioLoadError(
            f"CSVに必須カラムがありません: {', '.join(missing_columns)}\n"
            f"必須カラム: {', '.join(REQUIRED_COLUMNS)}"
        )

    if df.empty:
        raise PortfolioLoadError("保有銘柄データが1件もありません")

    df["code"] = df["code"].str.strip()

    for numeric_col in ("purchase_price", "quantity"):
        df[numeric_col] = pd.to_numeric(df[numeric_col], errors="coerce")
        invalid_rows = df[df[numeric_col].isna()]
        if not invalid_rows.empty:
            invalid_codes = ", ".join(invalid_rows["code"].fillna("(不明)"))
            raise PortfolioLoadError(
                f"'{numeric_col}' が数値として解釈できない行があります: {invalid_codes}"
            )

    df["purchase_date"] = pd.to_datetime(df["purchase_date"], errors="coerce")
    if df["purchase_date"].isna().any():
        invalid_codes = ", ".join(df.loc[df["purchase_date"].isna(), "code"])
        logger.warning(
            "purchase_date を日付として解釈できない行があります（処理は継続します）: %s",
            invalid_codes,
        )

    return df.reset_index(drop=True)


def _clean_number(raw: str) -> Optional[float]:
    """楽天証券CSVの数値セル（桁区切りカンマ・"-"等）をfloatに変換する。"""
    raw = raw.strip().strip('"')
    if raw in ("", "-", "―", "—"):
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _parse_rakuten_format(text: str) -> pd.DataFrame:
    """楽天証券「資産残高」エクスポート形式（複数セクション帳票）を読み込む。"""
    rows = list(csv.reader(io.StringIO(text)))

    records: list[dict] = []
    skipped_codes: list[str] = []
    current_section: Optional[str] = None
    column_index: Optional[dict[str, int]] = None

    for row in rows:
        if not row or all(cell.strip() == "" for cell in row):
            column_index = None
            continue

        first_cell = row[0].strip()

        if first_cell.startswith(_SECTION_MARKER_PREFIX):
            current_section = first_cell.lstrip(_SECTION_MARKER_PREFIX).strip()
            column_index = None
            continue

        if first_cell == _CODE_LABEL:
            # セクションごとに列構成が異なるため、都度ヘッダから列位置を読み取る
            column_index = {name.strip(): idx for idx, name in enumerate(row)}
            continue

        if column_index is None:
            # セクション見出し・帳票冒頭のサマリ行など、対象外の行は無視する
            continue

        if first_cell == "":
            # 「特定口座合計」等の集計行。このセクションのデータ行は終了
            column_index = None
            continue

        if _NAME_LABEL not in column_index or _QUANTITY_LABEL not in column_index:
            continue

        try:
            code = row[column_index[_CODE_LABEL]].strip()
            name = row[column_index[_NAME_LABEL]].strip()
            quantity = _clean_number(row[column_index[_QUANTITY_LABEL]])
            price_idx = column_index.get(_PRICE_LABEL)
            purchase_price = _clean_number(row[price_idx]) if price_idx is not None else None
        except IndexError:
            continue

        if not code or quantity is None or purchase_price is None:
            skipped_codes.append(code or "(不明)")
            continue

        records.append(
            {
                "code": code,
                "name": name,
                "purchase_price": purchase_price,
                "quantity": quantity,
                "purchase_date": pd.NaT,
                "account": current_section or "",
            }
        )

    if skipped_codes:
        logger.warning(
            "数量・平均取得価額が読み取れず読み飛ばした銘柄があります: %s",
            ", ".join(skipped_codes),
        )

    if not records:
        raise PortfolioLoadError(
            "楽天証券の資産残高CSVから保有銘柄を1件も抽出できませんでした。"
            "フォーマットが変更されている可能性があります。"
        )

    df = pd.DataFrame.from_records(records)
    accounts = "・".join(sorted(set(df["account"])) or ["(不明)"])
    logger.info(
        "楽天証券の資産残高CSV形式として読み込みました: %d件 (口座区分: %s)",
        len(df),
        accounts,
    )
    return df.reset_index(drop=True)


def _parse_trade_history_format(text: str) -> pd.DataFrame:
    """楽天証券「取引履歴」エクスポート形式を集計し、現在の保有銘柄を算出する。

    口座区分・銘柄コードごとに約定日の昇順で取引を処理し、移動平均法で
    取得総額を積み上げる。

    - 買付: 受渡金額（手数料・税込）を取得総額に加算（受渡金額が無い場合は
      単価×数量で代用）
    - 売付: その時点の平均取得単価×売却数量ぶんを取得総額から控除
    - 入庫/出庫: 株式分割等による数量調整であるケースが多いため、
      取得総額は据え置いたまま数量のみ増減させる（真に取得コストが
      発生する移管の場合は取得単価が実態と乖離しうる）
    - 信用区分が現物以外（信用取引）の行は保有株数に影響しないため除外

    処理後、数量が0より大きい（現在保有中の）銘柄のみを返す。

    Args:
        text: デコード済みのCSVテキスト。

    Returns:
        pd.DataFrame: code, name, purchase_price, quantity, purchase_date
            （現ポジションを開始した約定日の推定値。判定できない場合はNaT）,
            account 列を持つDataFrame。

    Raises:
        PortfolioLoadError: 必須カラムが欠落している、または集計の結果
            現在保有中の銘柄が1件もない場合。
    """
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise PortfolioLoadError("CSVファイルが空です")

    header = rows[0]
    column_index = {name.strip(): idx for idx, name in enumerate(header)}
    missing = [label for label in _TRADE_REQUIRED_LABELS if label not in column_index]
    if missing:
        raise PortfolioLoadError(
            f"取引履歴CSVに必須カラムがありません: {', '.join(missing)}"
        )
    settlement_idx = column_index.get(_TRADE_SETTLEMENT_LABEL)
    margin_idx = column_index.get(_TRADE_MARGIN_LABEL)

    def _parse_trade_date(raw: str) -> Optional[datetime]:
        raw = raw.strip().strip('"')
        try:
            return datetime.strptime(raw, "%Y/%m/%d")
        except ValueError:
            return None

    data_rows = [row for row in rows[1:] if any(cell.strip() for cell in row)]

    parsed_rows = []
    unparseable_dates = 0
    for row in data_rows:
        trade_date = _parse_trade_date(row[column_index[_TRADE_DATE_LABEL]])
        if trade_date is None:
            unparseable_dates += 1
            continue
        parsed_rows.append((trade_date, row))
    if unparseable_dates:
        logger.warning(
            "約定日を解釈できず読み飛ばした取引が%d件あります", unparseable_dates
        )
    parsed_rows.sort(key=lambda item: item[0])

    positions: dict[tuple[str, str], dict] = {}
    margin_skipped = 0
    unhandled_side_codes: set[str] = set()
    oversell_codes: set[str] = set()
    deposit_withdrawal_count = 0

    for trade_date, row in parsed_rows:
        margin = row[margin_idx].strip() if margin_idx is not None else "-"
        if margin not in ("-", ""):
            margin_skipped += 1
            continue

        code = row[column_index[_CODE_LABEL]].strip()
        name = row[column_index[_NAME_LABEL]].strip()
        account_raw = row[column_index[_TRADE_ACCOUNT_LABEL]].strip()
        account = _ACCOUNT_LABEL_ALIASES.get(account_raw, account_raw)
        side = row[column_index[_TRADE_SIDE_LABEL]].strip()
        quantity = _clean_number(row[column_index[_TRADE_QUANTITY_LABEL]]) or 0.0
        price = _clean_number(row[column_index[_TRADE_PRICE_LABEL]]) or 0.0
        settlement = (
            _clean_number(row[settlement_idx]) if settlement_idx is not None else None
        )

        key = (code, account)
        position = positions.setdefault(
            key,
            {"name": name, "quantity": 0.0, "total_cost": 0.0, "opened_date": None},
        )
        position["name"] = name  # 銘柄名変更があれば最新のものを使用

        if side == "買付":
            if position["quantity"] <= 1e-9:
                # ゼロから買い増した日＝現在の保有ポジションを開始した日とみなす
                position["opened_date"] = trade_date
            cost = settlement if settlement is not None else price * quantity
            position["quantity"] += quantity
            position["total_cost"] += cost
        elif side in ("入庫", "出庫"):
            if side == "入庫" and position["quantity"] <= 1e-9:
                position["opened_date"] = trade_date
            deposit_withdrawal_count += 1
            sign = 1 if side == "入庫" else -1
            position["quantity"] = max(0.0, position["quantity"] + sign * quantity)
        elif side == "売付":
            if position["quantity"] <= 0:
                oversell_codes.add(code)
                continue
            avg_price = position["total_cost"] / position["quantity"]
            sell_quantity = min(quantity, position["quantity"])
            position["quantity"] -= sell_quantity
            position["total_cost"] -= avg_price * sell_quantity
        else:
            unhandled_side_codes.add(f"{code}:{side}")

    if margin_skipped:
        logger.info(
            "信用取引の行は現物保有に影響しないため%d件除外しました", margin_skipped
        )
    if deposit_withdrawal_count:
        logger.warning(
            "入庫/出庫を%d件検出しました。株式分割等による数量調整と仮定し、"
            "取得総額は据え置いて集計しています（実際の平均取得価額と誤差が生じる場合があります）",
            deposit_withdrawal_count,
        )
    if oversell_codes:
        logger.warning(
            "保有数量を超える売却を検出し無視しました（取引履歴が不完全な可能性）: %s",
            ", ".join(sorted(oversell_codes)),
        )
    if unhandled_side_codes:
        logger.warning(
            "未対応の売買区分を含む行を読み飛ばしました: %s",
            ", ".join(sorted(unhandled_side_codes)),
        )

    records = []
    for (code, account), position in positions.items():
        if position["quantity"] <= 1e-9:
            continue
        opened_date = position["opened_date"]
        records.append(
            {
                "code": code,
                "name": position["name"],
                "purchase_price": round(position["total_cost"] / position["quantity"], 2),
                "quantity": position["quantity"],
                # 現在の保有ポジションを開始した約定日（推定）。不明な場合はNaT
                "purchase_date": pd.Timestamp(opened_date) if opened_date else pd.NaT,
                "account": account,
            }
        )

    if not records:
        raise PortfolioLoadError(
            "取引履歴から現在の保有銘柄を1件も算出できませんでした。"
            "すべての銘柄が売却済みか、フォーマットが変更されている可能性があります。"
        )

    df = pd.DataFrame.from_records(records)
    logger.info(
        "楽天証券の取引履歴CSV形式として集計しました: 現在保有%d件"
        "（取得単価は移動平均法による概算値です。株式分割等の影響で実際の値と誤差が生じる場合があります）",
        len(df),
    )
    return df.reset_index(drop=True)


def load_portfolio(csv_path: str) -> pd.DataFrame:
    """保有銘柄CSVを読み込み、検証済みの DataFrame を返す。

    以下3形式のいずれであるかをファイル内容から自動判別して読み込む。
    - シンプル形式（code, name, purchase_price, quantity, purchase_date）
    - 楽天証券の資産残高エクスポート形式（assetbalance_*.csv）
    - 楽天証券の取引履歴エクスポート形式（tradehistory*.csv、集計して現在の
      保有銘柄を算出）

    Args:
        csv_path: 保有銘柄CSV（または取引履歴CSV）ファイルパス。

    Returns:
        pd.DataFrame: 検証・型変換済みの保有銘柄データ。少なくとも
            code, name, purchase_price, quantity, purchase_date 列を含む。
            楽天証券形式・取引履歴形式の場合は口座区分を示す account 列も含む。

    Raises:
        PortfolioLoadError: ファイルが存在しない、文字コードを判別できない、
            必須カラムが欠落している、または内容から保有銘柄を抽出できない場合。
    """
    path = Path(csv_path)
    if not path.exists():
        raise PortfolioLoadError(f"CSVファイルが見つかりません: {csv_path}")

    text = _read_text(path)

    if _looks_like_simple_format(text):
        df = _parse_simple_format(text)
    elif _looks_like_trade_history_format(text):
        df = _parse_trade_history_format(text)
    else:
        df = _parse_rakuten_format(text)

    logger.info("保有銘柄CSVを読み込みました: %d件 (%s)", len(df), csv_path)
    return df
