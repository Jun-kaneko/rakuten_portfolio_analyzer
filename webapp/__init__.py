"""ポートフォリオ分析システムのWeb GUI（FastAPI）。

既存のCLI用モジュール（analyzer.py, portfolio_loader.py, preferences.py,
price_fetcher.py, news_fetcher.py, config.py）はサービス層としてそのまま
再利用し、その上にREST APIとバックグラウンドジョブ機構を提供する。
main.py（CLI）は一切importしない・されない一方向依存を維持する。
"""
