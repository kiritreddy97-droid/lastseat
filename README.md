# LastSeat India

> A subscription for last-minute empty seats, from about Rs 500 plus taxes.

Idea from a creator video: seats on departing flights earn nothing once the plane leaves. Frontier Airlines' GoWild pass does this in the US; the idea is an Indian equivalent, e.g. an annual pass of Rs 25,000 for last-minute fares near Rs 500 plus taxes.

## What is in this repo
| Path | Purpose |
|---|---|
| `docs/` | Business plan, product requirements, architecture, roadmap, legal checklist, go-to-market, financial model, cloud setup |
| `backend/app/` | FastAPI service: `services.py` (business rules), `flows.py` (payments/OTP/refund orchestration), `main.py` (routes), provider interfaces `payments.py`, `otp.py`, `notifications.py` |
| `backend/migrations/` | Alembic migrations |
| `backend/tests/` | Unit tests for every business rule, plus end-to-end API tests (auth failures, payments, bump and priority flow) and a migration check |
| `web/index.html` | Draft landing page |
| `finance/model.py` | Editable unit-economics model |
| `Dockerfile`, `docker-compose.yml`, `render.yaml` | Container and cloud deployment |
| `.github/workflows/ci.yml` | Lint, test, build on every push |
| `.devcontainer/` | Cloud dev environment (GitHub Codespaces) |

## Quick start
```bash
cd backend
pip install -r requirements-dev.txt
alembic upgrade head              # create the schema (SQLite file by default)
pytest
uvicorn app.main:app --reload     # http://localhost:8000/docs
```
With Postgres: `docker compose up --build` (migrations run on start).

Local login: `POST /auth/otp/request`, then read the code from the server log (dev console sender), then `POST /auth/otp/verify`. Settings are in `.env.example`.

## Status
Launchable **pilot MVP** with stand-in integrations: OTP login + JWT, partner API keys, Alembic migrations, timezone-aware time, payment/notification/OTP interfaces with fakes, signed payment webhook, refunds and priority rebooking for bumped members, rate limiting and JSON logging. CI runs lint, tests and migrations on Postgres.

Not done because it needs your accounts or agreements: a real payment gateway, SMS provider, an airline partner and a deployment. See `docs/09-owner-checklist.md`; the engineering checklist is in `docs/03-architecture.md`.

Start reading at `docs/01-business-plan.md`.
