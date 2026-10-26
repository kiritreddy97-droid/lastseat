# LastSeat India

> A subscription for last-minute empty seats, from about Rs 500 plus taxes.

Idea from a creator video: seats on departing flights earn nothing once the plane leaves. Frontier Airlines' GoWild pass does this in the US; the idea is an Indian equivalent, e.g. an annual pass of Rs 25,000 for last-minute fares near Rs 500 plus taxes.

## What is in this repo
| Path | Purpose |
|---|---|
| `docs/` | Business plan, product requirements, architecture, roadmap, legal checklist, go-to-market, financial model, cloud setup |
| `backend/app/` | FastAPI service: `models.py`, `services.py` (business rules), `main.py` (routes) |
| `backend/tests/` | Unit tests for every business rule, plus an API smoke test |
| `web/index.html` | Draft landing page |
| `finance/model.py` | Editable unit-economics model |
| `Dockerfile`, `docker-compose.yml`, `render.yaml` | Container and cloud deployment |
| `.github/workflows/ci.yml` | Lint, test, build on every push |
| `.devcontainer/` | Cloud dev environment (GitHub Codespaces) |

## Quick start
```bash
cd backend
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload     # http://localhost:8000/docs
```
With Postgres: `docker compose up --build`.

## Status
Backend MVP of the core rules is implemented and tested. Not production-ready: authentication, migrations, payments and integrations are listed as to-do in `docs/03-architecture.md`.

Start reading at `docs/01-business-plan.md`.
