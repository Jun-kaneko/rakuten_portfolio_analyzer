"""指標計算とClaude APIによるポートフォリオ分析を行うモジュール。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from anthropic import Anthropic, APIError

from config import Config
from preferences import DEFAULT_SCORE
from price_fetcher import to_ticker

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Claude APIによる分析処理に失敗した場合に送出する例外。"""


def build_metrics(
    df: pd.DataFrame,
    prices: dict[str, dict],
    preferences: dict[str, int] | None = None,
) -> pd.DataFrame:
    """保有銘柄DataFrameに現在株価ベースの指標・愛着度・保有期間を付与する。

    Args:
        df: portfolio_loader.load_portfolio() で読み込んだDataFrame。
        prices: price_fetcher.fetch_prices_for_portfolio() の結果
            （ティッカーをキーとした株価情報の辞書）。
        preferences: preferences.load_preferences() の結果（銘柄コード→
            愛着度スコア1〜100の辞書）。未設定の銘柄は DEFAULT_SCORE を適用する。

    Returns:
        pd.DataFrame: 現在株価・評価額・含み損益・損益率・PER・PBR・愛着度・
            保有日数を付与したDataFrame。株価取得に失敗した銘柄は該当列が
            NaNになる。購入日が不明な銘柄は保有日数もNaNになる。
    """
    metrics = df.copy()
    metrics["ticker"] = metrics["code"].apply(to_ticker)

    def _lookup(ticker: str, key: str):
        entry = prices.get(ticker)
        return entry.get(key) if entry else None

    metrics["current_price"] = metrics["ticker"].apply(lambda t: _lookup(t, "price"))
    metrics["change_pct"] = metrics["ticker"].apply(lambda t: _lookup(t, "change_pct"))
    metrics["per"] = metrics["ticker"].apply(lambda t: _lookup(t, "per"))
    metrics["pbr"] = metrics["ticker"].apply(lambda t: _lookup(t, "pbr"))

    metrics["market_value"] = metrics["current_price"] * metrics["quantity"]
    metrics["unrealized_pl"] = (
        metrics["current_price"] - metrics["purchase_price"]
    ) * metrics["quantity"]
    metrics["pl_pct"] = (
        (metrics["current_price"] - metrics["purchase_price"]) / metrics["purchase_price"] * 100
    )

    missing = metrics[metrics["current_price"].isna()]
    if not missing.empty:
        logger.warning(
            "現在株価が取得できなかった銘柄は指標を計算できません: %s",
            ", ".join(missing["code"]),
        )

    if "account" not in metrics.columns:
        # シンプル形式（口座区分の概念が無いCSV）では空文字で埋める
        metrics["account"] = ""

    preferences = preferences or {}
    metrics["affection_score"] = (
        metrics["code"].map(preferences).fillna(DEFAULT_SCORE).astype(int)
    )
    missing_pref_codes = metrics.loc[~metrics["code"].isin(preferences), "code"].unique()
    if len(missing_pref_codes) > 0:
        logger.info(
            "愛着度未設定の銘柄はデフォルト値%dを適用しました: %s",
            DEFAULT_SCORE,
            ", ".join(missing_pref_codes),
        )

    if "purchase_date" in metrics.columns:
        holding_days = (pd.Timestamp.now().normalize() - metrics["purchase_date"]).dt.days
        metrics["holding_days"] = holding_days.where(holding_days >= 0)
    else:
        metrics["holding_days"] = pd.NA

    return metrics


def _format_portfolio_table(metrics: pd.DataFrame, total_market_value: float) -> str:
    """Claudeへのプロンプトに埋め込むための保有銘柄テーブルをMarkdown形式で作る。

    Args:
        metrics: build_metrics() で算出した指標付きDataFrame。
        total_market_value: _compute_portfolio_summary() が返す
            total_market_value。行ごとの「構成比」列の分母として使用する。
    """
    has_account = "account" in metrics.columns and metrics["account"].astype(bool).any()
    has_holding_days = "holding_days" in metrics.columns and metrics["holding_days"].notna().any()
    weights = _compute_position_weights(metrics, total_market_value)

    header_cols = ["銘柄コード", "銘柄名"]
    if has_account:
        header_cols.append("口座区分")
    header_cols += [
        "取得単価", "現在株価", "数量", "評価額", "構成比",
        "含み損益", "損益率", "PER", "PBR", "愛着度",
    ]
    if has_holding_days:
        header_cols.append("保有期間")
    lines = [
        "| " + " | ".join(header_cols) + " |",
        "|" + "---|" * len(header_cols),
    ]

    def _fmt(value, spec="{:.2f}"):
        if value is None or pd.isna(value):
            return "N/A"
        return spec.format(value)

    def _fmt_holding_days(days):
        if days is None or pd.isna(days):
            return "不明"
        years = days / 365
        return f"約{years:.1f}年" if years >= 1 else f"{int(days)}日"

    for idx, row in metrics.iterrows():
        cells = [row["code"], row["name"]]
        if has_account:
            cells.append(row.get("account") or "-")
        cells += [
            _fmt(row["purchase_price"]),
            _fmt(row["current_price"]),
            str(int(row["quantity"])),
            _fmt(row["market_value"]),
            f"{_fmt(weights.loc[idx])}%",
            _fmt(row["unrealized_pl"]),
            f"{_fmt(row['pl_pct'])}%",
            _fmt(row["per"]),
            _fmt(row["pbr"]),
            f"{int(row['affection_score'])}/100",
        ]
        if has_holding_days:
            cells.append(_fmt_holding_days(row.get("holding_days")))
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines)


def _format_news_date(raw) -> str:
    """ニュースの公開日時（ISO文字列 or UNIXタイムスタンプ）を YYYY-MM-DD 形式にする。"""
    if raw is None:
        return "日時不明"
    try:
        if isinstance(raw, (int, float)):
            dt = datetime.fromtimestamp(raw, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return "日時不明"


def _format_news_section(metrics: pd.DataFrame, news: dict[str, list[dict]]) -> str:
    """Claudeへのプロンプトに埋め込むための銘柄別最新ニュースをMarkdown形式で作る。"""
    lines = []
    for _, row in metrics.iterrows():
        items = news.get(row["ticker"], [])
        lines.append(f"### {row['name']}（{row['code']}）")
        if not items:
            lines.append("- 関連ニュースは見つかりませんでした。")
            continue
        for item in items:
            date_str = _format_news_date(item.get("published_at"))
            title = item.get("title", "(タイトル不明)")
            publisher = item.get("publisher") or "不明"
            lines.append(f"- [{date_str}] {title}（{publisher}）")
    return "\n".join(lines)


def _compute_position_weights(metrics: pd.DataFrame, total_market_value: float) -> pd.Series:
    """各ポジション（1行＝1銘柄1口座区分）の全体構成比(%)をPythonで正確に計算する。

    Claudeにテーブルの生データから構成比・集中リスクを暗算させると誤りやすい
    ため、構成比は必ずここで決定的に計算し、_format_portfolio_table() の列
    として確定値のまま埋め込む。

    Args:
        metrics: build_metrics() で算出した指標付きDataFrame。
        total_market_value: _compute_portfolio_summary() が返す
            total_market_value（構成比の分母として使用する）。

    Returns:
        pd.Series: metricsと同じindexを持つ、行ごとの構成比(%)のSeries。
            現在株価が取得できていない行、またはtotal_market_valueが0の
            場合はNA（pd.NA）になる。
    """
    if not total_market_value:
        return pd.Series(pd.NA, index=metrics.index, dtype="Float64")
    return metrics["market_value"] / total_market_value * 100


def _compute_portfolio_summary(metrics: pd.DataFrame) -> dict:
    """ポートフォリオ全体の集計値をPythonで正確に計算する。

    LLMに多数の銘柄データを渡して合計・損益率の計算までさせると、
    特に軽量モデルでは合算ミスが起きやすいため、合計値は必ずここで
    決定的に計算し、プロンプトへは確定値として渡す。

    Args:
        metrics: build_metrics() で算出した指標付きDataFrame。

    Returns:
        dict: 評価額合計・取得総額合計・含み損益合計・加重損益率・
            保有銘柄数・株価取得失敗件数を含む辞書。
    """
    valid = metrics[metrics["current_price"].notna()]
    total_market_value = float(valid["market_value"].sum())
    total_purchase_amount = float((valid["purchase_price"] * valid["quantity"]).sum())
    total_unrealized_pl = float(valid["unrealized_pl"].sum())
    total_pl_pct = (
        total_unrealized_pl / total_purchase_amount * 100 if total_purchase_amount else 0.0
    )
    return {
        "total_market_value": total_market_value,
        "total_purchase_amount": total_purchase_amount,
        "total_unrealized_pl": total_unrealized_pl,
        "total_pl_pct": total_pl_pct,
        "num_holdings": len(metrics),
        "num_missing_price": int(metrics["current_price"].isna().sum()),
    }


def _format_portfolio_summary(summary: dict) -> str:
    """_compute_portfolio_summary() の結果をプロンプト埋め込み用に整形する。"""
    lines = [
        f"- 評価額合計: {summary['total_market_value']:,.0f}円",
        f"- 取得総額合計: {summary['total_purchase_amount']:,.0f}円",
        f"- 含み損益合計: {summary['total_unrealized_pl']:,.0f}円"
        f"（{summary['total_pl_pct']:+.2f}%）",
        f"- 保有銘柄数: {summary['num_holdings']}件",
    ]
    if summary["num_missing_price"] > 0:
        lines.append(
            f"- うち現在株価が取得できず集計から除外した銘柄: {summary['num_missing_price']}件"
        )
    return "\n".join(lines)


def _compute_cross_account_positions(
    metrics: pd.DataFrame, total_market_value: float
) -> pd.DataFrame:
    """同一銘柄コードが複数口座に分かれているポジションを口座横断で合算する。

    _format_portfolio_table() は口座区分ごとに行を分けて出力するため、
    Claudeにテーブルの生データから複数口座分の合算をさせると合算漏れが
    起きやすい（実例: オリエンタルランドで特定口座とNISA成長投資枠の
    合算漏れにより、本来約42.7%の構成比が約27.5%と誤って算出された）。
    そのため、口座横断の合算値は必ずここで決定的に計算し、プロンプトへは
    確定値として渡す。

    Args:
        metrics: build_metrics() で算出した指標付きDataFrame。
        total_market_value: _compute_portfolio_summary() が返す
            total_market_value（全体構成比の分母として使用する）。

    Returns:
        pd.DataFrame: 同一codeが2口座以上に分かれている銘柄のみを対象に、
            code, name, num_accounts, accounts, total_quantity,
            total_market_value, total_purchase_amount, total_unrealized_pl,
            total_pl_pct, weight_pct, has_missing_price_account を
            1銘柄1行で持つDataFrame（評価額の大きい順）。
            該当銘柄が無い場合は空のDataFrameを返す。
    """
    empty_columns = [
        "code", "name", "num_accounts", "accounts", "total_quantity",
        "total_market_value", "total_purchase_amount", "total_unrealized_pl",
        "total_pl_pct", "weight_pct", "has_missing_price_account",
    ]
    if "account" not in metrics.columns:
        return pd.DataFrame(columns=empty_columns)

    account_counts = metrics.groupby("code")["account"].nunique()
    multi_account_codes = account_counts[account_counts > 1].index
    if len(multi_account_codes) == 0:
        return pd.DataFrame(columns=empty_columns)

    valid = metrics[metrics["current_price"].notna()].copy()
    valid["purchase_amount"] = valid["purchase_price"] * valid["quantity"]
    subset = valid[valid["code"].isin(multi_account_codes)]
    if subset.empty:
        return pd.DataFrame(columns=empty_columns)

    grouped = subset.groupby("code").agg(
        name=("name", "first"),
        accounts=("account", lambda s: "・".join(sorted(set(a for a in s if a))) or "-"),
        num_accounts_with_price=("account", "nunique"),
        total_quantity=("quantity", "sum"),
        total_market_value=("market_value", "sum"),
        total_purchase_amount=("purchase_amount", "sum"),
        total_unrealized_pl=("unrealized_pl", "sum"),
    ).reset_index()

    grouped["num_accounts"] = grouped["code"].map(account_counts)
    grouped["has_missing_price_account"] = (
        grouped["num_accounts"] > grouped["num_accounts_with_price"]
    )
    grouped["total_pl_pct"] = grouped.apply(
        lambda r: r["total_unrealized_pl"] / r["total_purchase_amount"] * 100
        if r["total_purchase_amount"]
        else 0.0,
        axis=1,
    )
    grouped["weight_pct"] = (
        grouped["total_market_value"] / total_market_value * 100
        if total_market_value
        else pd.NA
    )
    return grouped.sort_values("total_market_value", ascending=False).reset_index(drop=True)


def _format_cross_account_positions(cross_positions: pd.DataFrame) -> str:
    """_compute_cross_account_positions() の結果をプロンプト埋め込み用に整形する。

    該当銘柄が無い場合は、Claudeが「複数口座保有銘柄の有無」を推測せず
    済むよう、その旨を明記した1行を返す。
    """
    if cross_positions.empty:
        return "複数口座にまたがって保有している銘柄はありません。"

    lines = [
        "| 銘柄コード | 銘柄名 | 口座数 | 口座内訳 | 合算数量 | 合算評価額 | "
        "合算取得総額 | 合算含み損益 | 合算損益率 | 全体構成比 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, row in cross_positions.iterrows():
        name = row["name"]
        if row["has_missing_price_account"]:
            name += "※"
        weight = f"{row['weight_pct']:.1f}%" if pd.notna(row["weight_pct"]) else "N/A"
        lines.append(
            f"| {row['code']} | {name} | {int(row['num_accounts'])} | {row['accounts']} | "
            f"{int(row['total_quantity'])} | {row['total_market_value']:,.0f}円 | "
            f"{row['total_purchase_amount']:,.0f}円 | {row['total_unrealized_pl']:,.0f}円 | "
            f"{row['total_pl_pct']:+.2f}% | {weight} |"
        )
    if cross_positions["has_missing_price_account"].any():
        lines.append("\n※一部口座で現在株価が取得できず、取得できた口座のみで合算しています。")
    return "\n".join(lines)


def _build_prompt(metrics: pd.DataFrame, news: dict[str, list[dict]] | None = None) -> str:
    summary_data = _compute_portfolio_summary(metrics)
    table = _format_portfolio_table(metrics, summary_data["total_market_value"])
    news = news or {}
    news_section = _format_news_section(metrics, news)
    summary = _format_portfolio_summary(summary_data)
    cross_account = _format_cross_account_positions(
        _compute_cross_account_positions(metrics, summary_data["total_market_value"])
    )
    return f"""あなたは日本株に精通した investment analyst です。
以下は個人投資家の保有ポートフォリオです。取得単価・現在株価・PER・PBR・
愛着度・保有期間・最新ニュース等の情報をもとに、日本語のMarkdownで
分析レポートを作成してください。

## ポートフォリオ集計値（Pythonで算出済みの正確な値）
{summary}

## 口座横断保有銘柄（Pythonで算出済みの正確な値）
同一銘柄が複数口座（特定口座・NISA成長投資枠など）に分かれている場合の
合算結果です。
{cross_account}

**重要**: 上記の集計値は既に正確に計算済みです。
- 「全体評価」セクションで言及する評価額合計・含み損益合計・損益率は、
  必ず「ポートフォリオ集計値」の数値をそのまま使用してください。
- 各銘柄の保有比率（構成比%）に言及する場合は、「保有銘柄データ」テーブルの
  「構成比」列、または複数口座に分かれている銘柄については上記
  「口座横断保有銘柄」テーブルの「全体構成比」列の数値をそのまま使用し、
  評価額から自分で割合を計算し直さないでください。
- 同一銘柄が複数口座に分かれている銘柄の集中リスクを議論する際は、
  必ず「口座横断保有銘柄」テーブルの合算値を使用してください。
  「保有銘柄データ」テーブルの口座別の行を自分で合算しないでください
  （合算漏れによる誤った集中リスク評価を防ぐためです）。

## 保有銘柄データ
{table}

## 各銘柄の最新ニュース（参考情報）
{news_section}

ニュースの扱いについて、以下に注意してください。
- Yahoo Financeから自動取得したニュースのため、銘柄と直接関係の薄い
  一般的な市況記事が混ざっていることがあります。銘柄名・事業内容と
  明らかに無関係な記事は無視してください。
- 決算・業績修正・不祥事・規制動向など、割安度判定や売却タイミングの
  判断に影響しうる重要な内容があれば、該当銘柄の分析に反映してください。
- 「関連ニュースは見つかりませんでした」の銘柄は、無理にニュースへ
  言及せず、他の指標のみで判断してください。

## 投資判断における個人的な方針（最重要・必ず反映してください）
この投資家には、一般的な割安度判断だけでは測れない以下の方針があります。

1. 好きな銘柄は基本的に売らない。愛着度が高い銘柄については追加購入の
   検討はあっても、含み損益や割高感を理由に売却を提案しないこと。
2. 長期保有していて「嫌いではない」程度の銘柄は売却を検討しうるが、
   いつ売るべきかの判断が難しいと感じている。

これを踏まえ、愛着度（1〜100、100が最も愛着が強い＝手放したくない）を
以下のように扱ってください。

- **愛着度80以上**：お気に入り。含み損益や割安度に関わらず売却は提案しない
  でください。追加購入すべきかという観点でのみコメントしてください。
- **愛着度50〜79**：保有期間が長い（目安1年以上）場合は「そろそろ売却を
  検討すべきか」を具体的な根拠（割高感、他に良い投資機会があるか、
  含み益を確定すべき水準か等）とともに判断材料を提示してください。
  売却タイミングの難しさを踏まえ、断定ではなく判断材料の提示を重視して
  ください。保有期間が短い、または不明な場合は無理に売却タイミングへ
  言及しなくてよいです。
- **愛着度49以下**：愛着が薄い銘柄です。入れ替え候補として積極的に
  検討対象に含めてください。

## レポートに含めるべき内容
以下の構成・見出しレベルで出力してください。

## ポートフォリオ分析結果
### 全体評価
冒頭で「ポートフォリオ集計値」に記載した評価額合計・含み損益合計・損益率を
そのまま提示したうえで、リスク傾向（セクター偏重・集中リスクなど）について
コメントしてください。集中リスクや保有比率に言及する際は、必ず「保有銘柄
データ」テーブルの構成比列、および「口座横断保有銘柄」テーブルの数値を
そのまま使用し、これらの数値を独自に再計算しないでください。

### 銘柄別分析
各銘柄について、`- 銘柄名（銘柄コード）：含み益/損X%、割安度：★の数（1〜5個、多いほど割安）、愛着度：X/100`
の形式で1行要約したうえで、上記の方針に沿った判定理由・アドバイスを
簡潔に補足してください。

### ポートフォリオ改善提案
セクター偏り・保有比率などの観点から改善案を提示してください。保有比率に
言及する際は「保有銘柄データ」テーブルの構成比列、または複数口座に分かれて
いる銘柄については「口座横断保有銘柄」テーブルの全体構成比をそのまま使用し
（自分で計算し直さないでください）、愛着度80以上の銘柄は入れ替え候補から
除外してください。

### 入れ替え候補銘柄の推奨理由
愛着度が低い銘柄を優先しつつ、売却を検討すべき銘柄があれば理由とともに
挙げ、代替候補があれば触れてください。愛着度80以上の銘柄は対象外です。
データが不十分な場合は推測である旨を明記してください。
"""


def analyze_portfolio(
    metrics: pd.DataFrame,
    config: Config,
    news: dict[str, list[dict]] | None = None,
) -> str:
    """Claude APIを用いてポートフォリオを分析し、Markdownレポートを返す。

    Args:
        metrics: build_metrics() で算出した指標付きDataFrame。
        config: Anthropic APIキー・モデル名を含む設定。
        news: news_fetcher.fetch_news_for_portfolio() の結果（ティッカーを
            キーとしたニュース記事リストの辞書）。省略時はニュース無しとして扱う。

    Returns:
        str: Claudeが生成したMarkdown形式の分析レポート。

    Raises:
        AnalysisError: Claude API呼び出しに失敗した場合。
    """
    client = Anthropic(api_key=config.anthropic_api_key)
    prompt = _build_prompt(metrics, news)

    try:
        # max_tokens が大きい場合、非ストリーミング呼び出しはSDK側のタイムアウト
        # ガード（10分超が見込まれる場合はエラー）に引っかかるため、常に
        # ストリーミングで呼び出す。
        with client.messages.stream(
            model=config.claude_model,
            max_tokens=config.claude_max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()
    except APIError as exc:
        raise AnalysisError(f"Claude API呼び出しに失敗しました: {exc}") from exc

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    markdown = "\n".join(text_parts).strip()
    if not markdown:
        raise AnalysisError("Claude APIから空の応答が返されました。")

    if response.stop_reason == "max_tokens":
        logger.warning(
            "Claudeの応答がmax_tokens（%d）に達し、途中で打ち切られた可能性があります。"
            "'.env'の CLAUDE_MAX_TOKENS を増やして再実行することを検討してください。",
            config.claude_max_tokens,
        )
        markdown += (
            "\n\n> ⚠️ **注意**: 出力トークン上限に達したため、この続きが"
            "切り詰められている可能性があります。`.env`の`CLAUDE_MAX_TOKENS`を"
            "増やして再実行することを検討してください。"
        )

    return markdown


# web_search_20260209（動的フィルタリング対応版）が使えるのは
# Opus 5/4.8/4.7/4.6・Sonnet 5・Sonnet 4.6系のモデルのみで、Haikuを含む
# それ以外のモデルでは非対応（400エラーになる）。日付サフィックス付きの
# モデルIDにも対応できるよう前方一致で判定する。
_WEB_SEARCH_DYNAMIC_FILTERING_MODEL_PREFIXES = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-fable-5",
    "claude-mythos-5",
)


def _web_search_tool_type(model: str) -> str:
    """使用モデルに応じて有効なweb_searchツールのtypeを返す。"""
    normalized = model.strip()
    for prefix in _WEB_SEARCH_DYNAMIC_FILTERING_MODEL_PREFIXES:
        if normalized == prefix or normalized.startswith(f"{prefix}-"):
            return "web_search_20260209"
    # Haiku等、上記以外のモデルは基本バージョンのみ対応
    return "web_search_20250305"


def _build_recommendation_prompt(metrics: pd.DataFrame, config: Config) -> str:
    """おすすめ新規投資候補を提案させるためのClaudeプロンプトを作る。"""
    total_market_value = _compute_portfolio_summary(metrics)["total_market_value"]
    table = _format_portfolio_table(metrics, total_market_value)
    return f"""あなたは日本株に精通した investment analyst です。
以下は個人投資家が現在保有しているポートフォリオです。

## 現在の保有銘柄データ
{table}

上記の保有状況（セクター偏重、割安度、含み損益の傾向など）を踏まえたうえで、
**現在保有していない**銘柄の中から、ポートフォリオ改善に資する新規投資候補を
{config.recommend_count}銘柄、web検索ツールを使って直近のニュース・業績動向・
株価水準を確認したうえで提案してください。

## 提案の観点
- 現在のポートフォリオが偏っているセクター・テーマがあれば、それを補う分散候補
- 割安度（PER・PBR等の指標）や直近の業績・株価モメンタムが良好な銘柄
- 日本株を中心としつつ、根拠があれば米国株等を含めても構いません
- 銘柄選定にあたっては、直近のニュースや決算情報をweb検索で確認し、
  古い情報や不確かな情報に基づく提案は避けてください

## 出力形式
以下の構成・見出しレベルでMarkdown形式で出力してください。

## おすすめ新規投資候補
### 選定方針
現在のポートフォリオの傾向を踏まえた選定方針を2〜3文で述べてください。

### 候補銘柄
候補銘柄ごとに以下の形式で記載してください。

- **銘柄名（銘柄コード）**
  - 直近の株価・業績動向（web検索で確認した内容を簡潔に）
  - 推奨理由（ポートフォリオ改善の観点から）
  - 留意点・リスク

### 免責事項
この提案はweb検索結果とAIの分析に基づく参考情報であり、投資助言ではない旨、
最終的な投資判断は自己責任で行うべき旨を明記してください。
"""


def recommend_stocks(metrics: pd.DataFrame, config: Config) -> str:
    """保有ポートフォリオの傾向を踏まえ、Claude APIとweb検索でおすすめ新規投資候補を提案する。

    Args:
        metrics: build_metrics() で算出した指標付きDataFrame。
        config: Anthropic APIキー・モデル名を含む設定。

    Returns:
        str: Claudeが生成したMarkdown形式のおすすめ銘柄セクション。

    Raises:
        AnalysisError: Claude API呼び出しに失敗した場合。
    """
    client = Anthropic(api_key=config.anthropic_api_key)
    prompt = _build_recommendation_prompt(metrics, config)
    messages: list[dict] = [{"role": "user", "content": prompt}]
    tools = [
        {
            "type": _web_search_tool_type(config.claude_model),
            "name": "web_search",
            "max_uses": config.recommend_web_search_max_uses,
        }
    ]

    # web_searchはサーバーサイドツールのためクライアント側でtool_useを処理する
    # 必要はないが、検索ラウンドがサーバー側の上限に達すると stop_reason が
    # "pause_turn" になるため、その場合は会話をそのまま再送して続行させる。
    response = None
    for _ in range(3):
        try:
            # max_tokens が大きい場合の非ストリーミング呼び出しタイムアウト
            # ガードを回避するため、常にストリーミングで呼び出す。
            with client.messages.stream(
                model=config.claude_model,
                max_tokens=config.recommend_max_tokens,
                tools=tools,
                messages=messages,
            ) as stream:
                response = stream.get_final_message()
        except APIError as exc:
            raise AnalysisError(f"Claude API呼び出しに失敗しました（おすすめ銘柄提案）: {exc}") from exc

        if response.stop_reason != "pause_turn":
            break
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response.content},
        ]

    if response is None:
        raise AnalysisError("Claude APIから応答が得られませんでした（おすすめ銘柄提案）。")

    if response.stop_reason == "refusal":
        logger.warning("おすすめ銘柄提案がClaudeに拒否されました（stop_reason=refusal）。")
        return (
            "## おすすめ新規投資候補\n\n"
            "> ⚠️ 今回はおすすめ銘柄の提案を生成できませんでした（Claudeが応答を拒否しました）。"
        )

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    markdown = "\n".join(text_parts).strip()
    if not markdown:
        raise AnalysisError("Claude APIから空の応答が返されました（おすすめ銘柄提案）。")

    if response.stop_reason == "max_tokens":
        logger.warning(
            "おすすめ銘柄提案の応答がmax_tokens（%d）に達し、途中で打ち切られた可能性があります。"
            "'.env'の RECOMMEND_MAX_TOKENS を増やして再実行することを検討してください。",
            config.recommend_max_tokens,
        )
        markdown += (
            "\n\n> ⚠️ **注意**: 出力トークン上限に達したため、この続きが"
            "切り詰められている可能性があります。`.env`の`RECOMMEND_MAX_TOKENS`を"
            "増やして再実行することを検討してください。"
        )

    return markdown


def save_report(markdown: str, output_path: str) -> None:
    """分析レポートをMarkdownファイルとして保存する。

    Args:
        markdown: analyze_portfolio() が返したMarkdown文字列。
        output_path: 保存先ファイルパス。
    """
    header = f"<!-- 生成日時: {datetime.now().isoformat(timespec='seconds')} -->\n\n"
    path = Path(output_path)
    path.write_text(header + markdown + "\n", encoding="utf-8")
    logger.info("分析レポートを保存しました: %s", output_path)
