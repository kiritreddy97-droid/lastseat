# Owner checklist: what only you can do

The code is a launchable pilot MVP. These steps need your accounts, money or legal standing; nothing here is stored in the repo.

## 1. Deploy to Render (staging pilot)
1. Render > New > Blueprint > pick this repo. `render.yaml` creates the API and Postgres and generates `JWT_SECRET`, `PAYMENT_WEBHOOK_SECRET` and `ADMIN_API_KEY` for you.
2. Migrations run automatically on each deploy.
3. Read `ADMIN_API_KEY` from the service's environment page, then create an airline partner:
   `curl -X POST $URL/admin/partners -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" -d '{"name":"Demo Air"}'`. The API key is shown once.
4. This deployment is `APP_ENV=staging`: payments are fake and login codes appear in the service logs. Use it for demos and dry runs with friendly users only; it must not take real money.

## 2. Payment gateway (e.g. Razorpay)
- Open a merchant account and complete KYC; confirm that selling a prepaid annual pass and per-flight fares is permitted under your category.
- Implement `PaymentGateway` in `backend/app/payments.py` (order, charge via saved mandate/UPI AutoPay or checkout, idempotent refund, webhook signature check) and select it in `providers.py` with `PAYMENT_GATEWAY`.
- Set the webhook URL to `/webhooks/payments` and `PAYMENT_WEBHOOK_SECRET` to the gateway's secret. Map the gateway's capture event to the `payment.captured` payload the handler expects.
- Decide the cancellation refund policy (today cancelling gives the seat back but does **not** refund; only airline bumps refund).

## 3. SMS / email for login codes and bump notices
- Pick a provider (DLT-registered sender and templates are required for SMS in India), implement `OtpSender` (`app/otp.py`) and `Notifier` (`app/notifications.py`), wire them in `providers.py`, set `OTP_SENDER`.

## 4. Airline partnership
- No airline has agreed yet. You need a written agreement covering: seat release rules, who bears a bump, refund responsibility, data sharing and the DGCA/consumer-law position (see `05-legal-compliance.md`). Until then the partner API is exercised only with a demo partner.
- Agree how they will push seat counts (this API, or a file/feed adapter you add).

## 5. Going to production
- Set `APP_ENV=production` only after steps 2 and 3: the app refuses to start with dev secrets, the fake gateway or console OTP.
- Move to a paid Render plan (free Postgres expires), enable backups, add error tracking (Sentry DSN), and use a custom domain with HTTPS.
- Rotate `JWT_SECRET` and `ADMIN_API_KEY` if they were ever shared. Rotating `JWT_SECRET` logs everyone out.
- Get legal review of terms (unguaranteed seats, bumps, refunds) and privacy policy (DPDP Act).
