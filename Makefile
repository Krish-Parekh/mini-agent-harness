.PHONY: dev db backend frontend install

UVICORN := uv run uvicorn backend.app:app --reload --port 8000 --reload-dir backend --reload-dir miniagent

# Start Postgres (required by the API).
db:
	docker compose up -d db

# FastAPI dev server. Reload is scoped to backend/ + miniagent/ so agent workspace
# edits under data/ do not restart the server.
backend:
	$(UVICORN)

# Next.js dev server (http://localhost:3000).
frontend:
	cd frontend && npm run dev

# Install Python and frontend dependencies.
install:
	uv sync
	cd frontend && npm install

# Start db, backend, and frontend together. Ctrl+C stops all three.
dev: db
	@trap 'kill 0' EXIT INT TERM; \
	$(UVICORN) & \
	cd frontend && npm run dev & \
	wait
