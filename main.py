"""ポートフォリオ分析システムのエントリーポイント。

実行フロー:
    1. CSV読み込み
    2. 現在株価取得
    3. 保有銘柄の最新ニュース取得
    4. 指標計算（PER, PBR, 損益率など）
    5. Claude API で分析
    6. 結果を整形して表示・保存
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from analyzer import (
    AnalysisError,
    analyze_portfolio,
    build_metrics,
    recommend_stocks,
    save_report,
)
from config import ConfigError, load_config
from news_fetcher import fetch_news_for_portfolio
from portfolio_loader import PortfolioLoadError, load_portfolio
from preferences import PreferencesLoadError, load_preferences
from price_fetcher import fetch_prices_for_portfolio

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="楽天証券形式の保有銘柄CSVから現在株価を取得し、Claude APIで割安度を分析します。"
    )
    parser.add_argument(
        "--portfolio",
        default="sample_portfolio.csv",
        help="保有銘柄CSVファイルのパス（デフォルト: sample_portfolio.csv）",
    )
    parser.add_argument(
        "--output",
        default="analysis_report.md",
        help="分析結果の出力先ファイルパス（デフォルト: analysis_report.md）",
    )
    parser.add_argument(
        "--preferences",
        default="stock_preferences.csv",
        help=(
            "銘柄ごとの愛着度設定CSVのパス（デフォルト: stock_preferences.csv）。"
            "ファイルが無い場合は全銘柄をデフォルト値として分析を続行する"
        ),
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="キャッシュ済みの株価・ニュースのみを使用し、Yahoo Financeへは問い合わせない",
    )
    parser.add_argument(
        "--no-news",
        action="store_true",
        help="保有銘柄の最新ニュース取得をスキップする（分析は指標のみで実施）",
    )
    parser.add_argument(
        "--no-recommend",
        action="store_true",
        help=(
            "保有ポートフォリオの傾向を踏まえたおすすめ新規投資候補の提案を"
            "スキップする（web検索を伴うため実行時間・コストを抑えたい場合に指定）"
        ),
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="ログレベル（DEBUG/INFO/WARNING/ERROR）。未指定時は設定値/デフォルトのINFOを使用",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # ロギングは設定読み込みより先に、まず暫定レベルでセットアップする
    logging.basicConfig(
        level=args.log_level or "INFO",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        config = load_config()
    except ConfigError as exc:
        logger.error(str(exc))
        return 1

    if args.log_level is None:
        logging.getLogger().setLevel(config.log_level)

    start_time = time.monotonic()

    try:
        df = load_portfolio(args.portfolio)
    except PortfolioLoadError as exc:
        logger.error("保有銘柄CSVの読み込みに失敗しました: %s", exc)
        return 1

    try:
        prices = fetch_prices_for_portfolio(df, config, cache_only=args.cache_only)
    except Exception as exc:  # noqa: BLE001 - 想定外のエラーもログに残して終了する
        logger.error("株価取得処理で予期しないエラーが発生しました: %s", exc, exc_info=True)
        return 1

    news: dict[str, list[dict]] = {}
    if args.no_news:
        logger.info("--no-news が指定されたため、ニュース取得をスキップします")
    else:
        try:
            news = fetch_news_for_portfolio(df, config, cache_only=args.cache_only)
        except Exception as exc:  # noqa: BLE001 - ニュース取得の失敗で分析全体は止めない
            logger.warning("ニュース取得処理で予期しないエラーが発生しました（分析は継続します）: %s", exc, exc_info=True)

    try:
        preferences = load_preferences(args.preferences)
    except PreferencesLoadError as exc:
        logger.error("愛着度設定CSVの読み込みに失敗しました: %s", exc)
        return 1

    metrics = build_metrics(df, prices, preferences)

    logger.info("Claude APIによる分析を開始します（モデル: %s）", config.claude_model)
    try:
        report_markdown = analyze_portfolio(metrics, config, news)
    except AnalysisError as exc:
        logger.error("Claude APIによる分析に失敗しました: %s", exc)
        return 1

    if args.no_recommend:
        logger.info("--no-recommend が指定されたため、おすすめ銘柄の提案をスキップします")
    elif args.cache_only:
        logger.info("--cache-only が指定されているため、web検索を伴うおすすめ銘柄の提案をスキップします")
    else:
        logger.info("おすすめ新規投資候補の提案を生成します")
        try:
            recommendation_markdown = recommend_stocks(metrics, config)
            report_markdown = report_markdown + "\n\n---\n\n" + recommendation_markdown
        except AnalysisError as exc:
            logger.warning("おすすめ銘柄の提案生成に失敗しました（分析結果は保存を継続します）: %s", exc)

    save_report(report_markdown, args.output)

    elapsed = time.monotonic() - start_time
    logger.info(
        "処理完了: 保有銘柄%d件 / 株価取得%d件 / ニュース取得%d銘柄 / 所要時間%.1f秒",
        len(df),
        len(prices),
        len(news),
        elapsed,
    )

    print("\n" + "=" * 60)
    print(report_markdown)
    print("=" * 60)
    print(f"\n分析レポートを保存しました: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
