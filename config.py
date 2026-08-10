"""アプリケーション設定の読み込みを行うモジュール。

環境変数（および .env ファイル）から Anthropic APIキーやデフォルトの
リトライ回数・タイムアウトなどを読み込み、Config オブジェクトとして
他のモジュールへ渡す。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    """設定値の読み込みに失敗した場合に送出する例外。"""


@dataclass
class Config:
    """アプリケーション全体で共有する設定値。"""

    anthropic_api_key: str
    claude_model: str = "claude-sonnet-5"
    claude_max_tokens: int = 8192
    price_fetch_timeout: int = 10
    price_fetch_retries: int = 3
    retry_backoff_seconds: float = 2.0
    cache_path: Path = Path("price_cache.json")
    news_fetch_timeout: int = 10
    news_fetch_retries: int = 3
    news_max_items: int = 3
    news_cache_path: Path = Path("news_cache.json")
    news_freshness_hours: float = 6.0
    recommend_max_tokens: int = 4096
    recommend_web_search_max_uses: int = 8
    recommend_count: int = 4
    log_level: str = "INFO"


def load_config() -> Config:
    """環境変数（.env を含む）から Config を構築する。

    Returns:
        Config: 読み込まれた設定値。

    Raises:
        ConfigError: ANTHROPIC_API_KEY が未設定の場合。
    """
    # .env ファイルが存在すれば読み込む（存在しなくてもエラーにはならない）
    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "ANTHROPIC_API_KEY が設定されていません。\n"
            "  1. `.env.example` を `.env` にコピーしてください。\n"
            "  2. `.env` 内の ANTHROPIC_API_KEY=your-key に実際のAPIキーを設定してください。\n"
            "  もしくは環境変数として直接 export してください。"
        )

    return Config(
        anthropic_api_key=api_key,
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"),
        claude_max_tokens=int(os.environ.get("CLAUDE_MAX_TOKENS", "8192")),
        price_fetch_timeout=int(os.environ.get("PRICE_FETCH_TIMEOUT", "10")),
        price_fetch_retries=int(os.environ.get("PRICE_FETCH_RETRIES", "3")),
        retry_backoff_seconds=float(os.environ.get("RETRY_BACKOFF_SECONDS", "2.0")),
        cache_path=Path(os.environ.get("PRICE_CACHE_PATH", "price_cache.json")),
        news_fetch_timeout=int(os.environ.get("NEWS_FETCH_TIMEOUT", "10")),
        news_fetch_retries=int(os.environ.get("NEWS_FETCH_RETRIES", "3")),
        news_max_items=int(os.environ.get("NEWS_MAX_ITEMS", "3")),
        news_cache_path=Path(os.environ.get("NEWS_CACHE_PATH", "news_cache.json")),
        news_freshness_hours=float(os.environ.get("NEWS_FRESHNESS_HOURS", "6.0")),
        recommend_max_tokens=int(os.environ.get("RECOMMEND_MAX_TOKENS", "4096")),
        recommend_web_search_max_uses=int(os.environ.get("RECOMMEND_WEB_SEARCH_MAX_USES", "8")),
        recommend_count=int(os.environ.get("RECOMMEND_COUNT", "4")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
