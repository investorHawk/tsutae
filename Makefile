# 薄い包み。中身は scripts/*.sh（Claude Code のサンドボックス内でも動くようにするため）
.PHONY: test lint format eval smoke dev-api dev-web seed

test:
	scripts/test.sh

lint:
	scripts/lint.sh

format:
	scripts/format.sh

# API を呼ぶ。サンドボックス外（先生が `! make eval`）で実行する
eval:
	scripts/eval.sh

smoke:
	.venv/bin/python scripts/smoke_agent_sdk.py

seed:
	.venv/bin/python scripts/seed_demo.py

dev-api:
	.venv/bin/uvicorn tsutae.api.app:app --reload --host 127.0.0.1 --port 8000 --app-dir backend --no-proxy-headers

dev-web:
	cd frontend && npx vite
