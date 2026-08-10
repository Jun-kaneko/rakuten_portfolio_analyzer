"""Yahoo Finance（yfinance）から現在株価を取得するモジュール。

同一銘柄の重複取得を避けるためのJSONキャッシュと、API障害時の
リトライ機能（最大N回・指数バックオフ）を備える。
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

logger = logging.getLogger(__name__)


def to_ticker(code: str) -> str:
    """銘柄コードをYahoo Finance用ティッカーに変換する。

    日本株を前提とし、サフィックスが無ければ ".T" を付与する。
    既に "." を含む場合（例: "9983.T", "AAPL"）はそのまま返す。

    Args:
        code: 楽天証券形式の銘柄コード（例: "9983"）。

    Returns:
        str: Yahoo Finance用ティッカーシンボル（例: "9983.T"）。
    """
    code = code.strip()
    if "." in code:
        return code
    return f"{code}.T"


class PriceCache:
    """株価取得結果をJSONファイルにキャッシュするクラス。

    同じ日に取得済みの銘柄は再取得せず、キャッシュを利用する。
    """

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
            logger.warning("キャッシュファイルの読み込みに失敗しました（無視して続行）: %s", exc)
            return {}

    def save(self) -> None:
        """現在のキャッシュ内容をJSONファイルへ書き出す。"""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("キャッシュファイルの書き込みに失敗しました: %s", exc)

    def get(self, ticker: str, *, fresh_within_hours: float = 12.0) -> Optional[dict]:
        """指定ティッカーの有効なキャッシュを返す（無ければ None）。"""
        entry = self._data.get(ticker)
        if entry is None:
            return None
        fetched_at = datetime.fromisoformat(entry["fetched_at"])
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        if age_hours > fresh_within_hours:
            return None
        return entry

    def set(self, ticker: str, data: dict) -> None:
        """指定ティッカーの取得結果をキャッシュに保存する。"""
        self._data[ticker] = data


def _fetch_from_yfinance(ticker: str, timeout: int) -> dict:
    """yfinanceから現在株価・前日比・PER/PBRを取得する（リトライなしの単発呼び出し）。"""
    ticker_obj = yf.Ticker(ticker)
    history = ticker_obj.history(period="5d", timeout=timeout)
    if history.empty:
        raise ValueError(f"株価データが取得できませんでした: {ticker}")

    closes = history["Close"].dropna()
    if closes.empty:
        raise ValueError(f"終値データが取得できませんでした: {ticker}")

    current_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else current_price
    change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close else 0.0

    # info の取得はティッカーによっては失敗・欠損することがあるため個別に保護する
    per = None
    pbr = None
    try:
        info = ticker_obj.info
        per = info.get("trailingPE")
        pbr = info.get("priceToBook")
    except Exception as exc:  # noqa: BLE001 - yfinance が投げる例外型が不定なため
        logger.warning("PER/PBR情報の取得に失敗しました（%s）: %s", ticker, exc)

    return {
        "ticker": ticker,
        "price": current_price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "per": per,
        "pbr": pbr,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_price(
    ticker: str,
    config: Config,
    cache: PriceCache,
    cache_only: bool = False,
) -> Optional[dict]:
    """1銘柄の現在株価を取得する（キャッシュ優先、失敗時は最大N回リトライ）。

    Args:
        ticker: Yahoo Finance用ティッカーシンボル。
        config: リトライ回数・バックオフ秒数等を含む設定。
        cache: 株価キャッシュ。
        cache_only: True の場合、キャッシュのみ参照しAPIは呼び出さない。

    Returns:
        Optional[dict]: 取得結果。取得不能な場合は None。
    """
    cached = cache.get(ticker)
    if cached is not None:
        logger.info("キャッシュを使用します: %s", ticker)
        return cached

    if cache_only:
        logger.warning("cache-only モードのためキャッシュが無い銘柄はスキップします: %s", ticker)
        return None

    last_error: Optional[Exception] = None
    for attempt in range(1, config.price_fetch_retries + 1):
        try:
            result = _fetch_from_yfinance(ticker, config.price_fetch_timeout)
            cache.set(ticker, result)
            logger.info("株価を取得しました: %s = %.2f円", ticker, result["price"])
            return result
        except Exception as exc:  # noqa: BLE001 - ネットワーク由来の例外型が不定なため
            last_error = exc
            logger.warning(
                "株価取得に失敗しました（%d/%d回目）: %s (%s)",
                attempt,
                config.price_fetch_retries,
                ticker,
                exc,
            )
            if attempt < config.price_fetch_retries:
                time.sleep(config.retry_backoff_seconds * attempt)

    logger.error("株価取得に最終的に失敗しました: %s (%s)", ticker, last_error)
    return None


def fetch_prices_for_portfolio(
    df: pd.DataFrame,
    config: Config,
    cache_only: bool = False,
) -> dict[str, dict]:
    """保有銘柄DataFrameの全銘柄について現在株価をまとめて取得する。

    Args:
        df: portfolio_loader.load_portfolio() で読み込んだDataFrame。
        config: アプリケーション設定。
        cache_only: True の場合、キャッシュ済み株価のみ使用する。

    Returns:
        dict[str, dict]: ティッカーをキーとした株価取得結果。
    """
    cache = PriceCache(config.cache_path)
    results: dict[str, dict] = {}

    # 複数口座で同一銘柄を保有している場合、ティッカーは重複しうる（結果はresultsで自動的に重複排除される）
    unique_tickers = {to_ticker(code) for code in df["code"]}

    for ticker in unique_tickers:
        result = fetch_price(ticker, config, cache, cache_only=cache_only)
        if result is not None:
            results[ticker] = result

    cache.save()
    logger.info(
        "株価取得完了: %d/%d 銘柄（保有行数: %d）", len(results), len(unique_tickers), len(df)
    )
    return results
