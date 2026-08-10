"""Yahoo Finance（yfinance）から保有銘柄の最新ニュースを取得するモジュール。

price_fetcher.py と同様、同一銘柄の重複取得を避けるJSONキャッシュと、
API障害時のリトライ機能（最大N回・指数バックオフ）を備える。ニュースは
株価よりも鮮度が重要な一方、値動きほど頻繁に更新されるものでもないため、
価格キャッシュより短めのデフォルト有効期限（6時間）を持つ。

注意: Yahoo Financeのニュースは日本の小型株では取得できない、または
銘柄と直接関係の薄い一般的な市況記事が混ざることがある。Claudeへの
プロンプト側で「関連性が薄い場合は無視する」よう指示することで対処する。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from config import Config
from price_fetcher import to_ticker

logger = logging.getLogger(__name__)


class NewsCache:
    """ニュース取得結果をJSONファイルにキャッシュするクラス。"""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("ニュースキャッシュの読み込みに失敗しました（無視して続行）: %s", exc)
            return {}

    def save(self) -> None:
        """現在のキャッシュ内容をJSONファイルへ書き出す。"""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("ニュースキャッシュの書き込みに失敗しました: %s", exc)

    def get(self, ticker: str, *, fresh_within_hours: float = 6.0) -> Optional[list[dict]]:
        """指定ティッカーの有効なキャッシュ済みニュース一覧を返す（無ければ None）。"""
        entry = self._data.get(ticker)
        if entry is None:
            return None
        fetched_at = datetime.fromisoformat(entry["fetched_at"])
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        if age_hours > fresh_within_hours:
            return None
        return entry["items"]

    def set(self, ticker: str, items: list[dict]) -> None:
        """指定ティッカーのニュース取得結果をキャッシュに保存する。"""
        self._data[ticker] = {
            "items": items,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }


def _extract_news_items(raw_news: list, max_items: int) -> list[dict]:
    """yfinanceのnews構造を正規化する。

    yfinanceのバージョンにより、記事情報が直下のキーにある形式と
    "content" キー配下にネストされた形式の両方が存在するため両対応する。
    """
    items: list[dict] = []
    for entry in (raw_news or [])[:max_items]:
        content = entry.get("content", entry)
        title = content.get("title") or entry.get("title")
        if not title:
            continue
        provider = content.get("provider") or {}
        canonical_url = content.get("canonicalUrl") or {}
        items.append(
            {
                "title": title,
                "publisher": provider.get("displayName") or entry.get("publisher") or "不明",
                "published_at": content.get("pubDate") or entry.get("providerPublishTime"),
                "url": canonical_url.get("url") or entry.get("link"),
            }
        )
    return items


def _fetch_from_yfinance(ticker: str, max_items: int) -> list[dict]:
    """yfinanceから当該銘柄の最新ニュースを取得する（リトライなしの単発呼び出し）。"""
    ticker_obj = yf.Ticker(ticker)
    raw_news = ticker_obj.news
    return _extract_news_items(raw_news, max_items)


def fetch_news(
    ticker: str,
    config: Config,
    cache: NewsCache,
    cache_only: bool = False,
) -> list[dict]:
    """1銘柄の最新ニュースを取得する（キャッシュ優先、失敗時は最大N回リトライ）。

    株価と異なり、ニュースが1件も無い・取得に失敗しても分析全体は継続
    できるべきであるため、最終的に失敗した場合は例外を投げず空リストを返す。

    Args:
        ticker: Yahoo Finance用ティッカーシンボル。
        config: リトライ回数・タイムアウト等を含む設定。
        cache: ニュースキャッシュ。
        cache_only: True の場合、キャッシュのみ参照しAPIは呼び出さない。

    Returns:
        list[dict]: ニュース記事のリスト（title, publisher, published_at, url）。
            取得できなかった場合は空リスト。
    """
    cached = cache.get(ticker, fresh_within_hours=config.news_freshness_hours)
    if cached is not None:
        logger.info("ニュースキャッシュを使用します: %s (%d件)", ticker, len(cached))
        return cached

    if cache_only:
        logger.warning("cache-only モードのためキャッシュが無い銘柄のニュースはスキップします: %s", ticker)
        return []

    last_error: Optional[Exception] = None
    for attempt in range(1, config.news_fetch_retries + 1):
        try:
            items = _fetch_from_yfinance(ticker, config.news_max_items)
            cache.set(ticker, items)
            logger.info("ニュースを取得しました: %s (%d件)", ticker, len(items))
            return items
        except Exception as exc:  # noqa: BLE001 - ネットワーク由来の例外型が不定なため
            last_error = exc
            logger.warning(
                "ニュース取得に失敗しました（%d/%d回目）: %s (%s)",
                attempt,
                config.news_fetch_retries,
                ticker,
                exc,
            )
            if attempt < config.news_fetch_retries:
                time.sleep(config.retry_backoff_seconds * attempt)

    # ニュースは補助情報のため、最終的に失敗しても分析自体は継続する
    logger.warning("ニュース取得に最終的に失敗しました（このままレポート作成を継続します）: %s (%s)", ticker, last_error)
    return []


def fetch_news_for_portfolio(
    df: pd.DataFrame,
    config: Config,
    cache_only: bool = False,
) -> dict[str, list[dict]]:
    """保有銘柄DataFrameの全銘柄について最新ニュースをまとめて取得する。

    Args:
        df: portfolio_loader.load_portfolio() で読み込んだDataFrame。
        config: アプリケーション設定。
        cache_only: True の場合、キャッシュ済みニュースのみ使用する。

    Returns:
        dict[str, list[dict]]: ティッカーをキーとしたニュース記事リスト
            （ニュースが1件も無い銘柄はキーごと含まれない）。
    """
    cache = NewsCache(config.news_cache_path)
    results: dict[str, list[dict]] = {}

    unique_tickers = {to_ticker(code) for code in df["code"]}
    for ticker in unique_tickers:
        items = fetch_news(ticker, config, cache, cache_only=cache_only)
        if items:
            results[ticker] = items

    cache.save()
    logger.info("ニュース取得完了: %d/%d 銘柄でニュースを取得", len(results), len(unique_tickers))
    return results
