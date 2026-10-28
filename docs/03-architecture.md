# LastSeat India: Architecture

```
 Web / mobile client
        |  HTTPS
   FastAPI service  (backend/app/main.py: routes, auth, rate limiting, request logging)
        |
   flows.py         (orchestration: OTP, payments, refunds, notifications behind interfaces)
        |
   services.py      (all business rules; pure functions over a DB session; unit-tested)
        |
   SQLAlchemy models --> PostgreSQL (SQLite for local dev and tests)
```

## Principles
- Business rules live in `services.py`, not in route handlers, so they are testable without HTTP.
- Time is passed in (`now`/`today`) so rules are deterministic in tests.
- Route handlers translate domain errors to HTTP status codes and commit the transaction.
- Money is stored in integer rupees or paise; never floats.

## Production hardening checklist

Done in code (no external credentials needed):
- [x] **Authentication.** Members log in with a one-time code (`POST /auth/otp/request`, `/auth/otp/verify`) and get a JWT (HS256, 24h, checked against the injectable clock). Codes are stored as HMACs, expire after 5 minutes, are single use and lock after 5 wrong guesses. Unknown accounts get the same response as known ones. The sender is an interface (`app/otp.py`); only a console sender exists.
- [x] **Roles.** `member` = Bearer JWT (`/me/*`, booking, cancel, own bookings only). `partner` = `X-API-Key` (`/partner/*`; keys are random, stored as SHA-256 hashes, and a partner can only touch its own flights). `admin` = `X-Admin-Key` from `ADMIN_API_KEY` (`/admin/*`; disabled when unset). Webhooks are authenticated by signature.
- [x] **Migrations.** Alembic (`backend/migrations`); `create_all` is gone. The container runs `alembic upgrade head` on start. CI applies, checks drift (`alembic check`), round-trips and runs the whole suite on Postgres 16. To change a model: `alembic revision --autogenerate -m "..."`, review the file, commit.
- [x] **Timezone-aware time.** All timestamps are timestamptz, read and written as aware UTC (`UTCDateTime` type). Naive datetimes are rejected on write and on the partner API. Routes get "now" from `app/clock.py`, so tests pin it.
- [x] **Payments (interface only).** `app/payments.py` defines `PaymentGateway` (order, charge, refund, webhook verification) with a `FakeGateway`. A pass is activated only by a signed `payment.captured` webhook (HMAC-SHA256 of the raw body in `X-Signature`), idempotent and amount-checked. Booking fares are charged through the gateway and refunded through it when a booking is bumped. A failed refund is recorded as `failed` and retried via `POST /admin/refunds/retry`; it never undoes the bump.
- [x] **Notifications (interface only).** `app/notifications.py`; bumps call it after the refund. A failing notifier does not fail the airline's request.
- [x] **Priority rebooking.** Bumping creates a `PriorityClaim` (48h) for the member on that route. On later flights on the same route, one seat per claimant is held back from general sale (search and booking), and claimants are exempt from the 6-booking cap. The hold is released 3 hours before departure so seats do not fly empty. One claim is used per booking.
- [x] **Rate limiting and logging.** Per-IP limits: 120 requests/min overall, 5/min on `/members` and `/auth/*` (env-tunable). Limits are in process memory, so move them to Redis or the host's edge before running more than one instance. Logs are one JSON object per line with a request id (`X-Request-ID` echoed back); OTP codes are logged only by the dev console sender.
- [x] **Startup guard.** With `APP_ENV=production` the app refuses to boot on the dev JWT/webhook secrets, the console OTP sender or the fake gateway.

Still open (needs the owner, see [09-owner-checklist.md](09-owner-checklist.md)):
- [ ] Real payment gateway adapter and merchant account; real SMS/email OTP and notification adapters.
- [ ] Error tracking (e.g. Sentry), database backups and a restore drill, secrets in the host's secret manager.
- [ ] Token revocation / refresh (JWTs are valid until they expire), CORS once a web client exists.
- [ ] Airline-specific integration (API or file feed) behind `/partner/*`, and legal sign-off ([05-legal-compliance.md](05-legal-compliance.md)).

## Environments
`local` (SQLite or docker compose Postgres), `staging` and `production` on a cloud host. See [08-cloud-deploy.md](08-cloud-deploy.md).
