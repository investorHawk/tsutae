"""HTTP API（FastAPI。docs/architecture.md §8・§8b）。

アプリは `tsutae.api.app.create_app()`（`uvicorn tsutae.api.app:app`）。
ここでは何も import しない（患者 API が pipeline を読み込まないようにするため）。
"""
