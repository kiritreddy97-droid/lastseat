"""End-to-end API tests: auth, payments, bookings, bumps, priority rebooking, limits."""
import json
from datetime import timedelta

import pytest

from app.config import Settings, settings
from app.payments import sign
from app.ratelimit import limiter

from .conftest import NOW

ADMIN = {"X-Admin-Key": "admin-test-key"}


def iso(hours):
    return (NOW + timedelta(hours=hours)).isoformat()


def login(env, email, name="Asha", phone=None):
    env.client.post("/members", json={"name": name, "email": email, "phone": phone})
    env.client.post("/auth/otp/request", json={"identifier": email})
    r = env.client.post("/auth/otp/verify", json={"identifier": email, "code": env.otp.last_code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def webhook(env, body: dict, signature=None):
    raw = json.dumps(body).encode()
    sig = sign(settings.webhook_secret, raw) if signature is None else signature
    return env.client.post("/webhooks/payments", content=raw, headers={"X-Signature": sig})


def buy_pass(env, headers):
    order = env.client.post("/me/pass/order", headers=headers).json()
    r = webhook(env, {"event": "payment.captured", "order_id": order["order_id"], "payment_id": "pay_1",
                      "amount_paise": order["amount_paise"]})
    assert r.json() == {"result": "ok"}
    return order


def partner(env, name="Demo Air"):
    key = env.client.post("/admin/partners", json={"name": name}, headers=ADMIN).json()["api_key"]
    return {"X-API-Key": key}


def publish(env, p, hours=20, seats=2, dest="GOI"):
    r = env.client.post("/partner/flights", headers=p, json={
        "airline": "Demo Air", "flight_no": "DA101", "origin": "BOM", "destination": dest,
        "departs_at": iso(hours), "open_seats": seats, "taxes_paise": 30_000})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- health / auth ---------------------------------------------------------------------------

def test_health_and_request_id(env):
    r = env.client.get("/health")
    assert r.json() == {"status": "ok"} and r.headers["x-request-id"]
    assert env.client.get("/health", headers={"X-Request-ID": "abc"}).headers["x-request-id"] == "abc"


def test_member_routes_reject_missing_bad_and_expired_tokens(env):
    assert env.client.get("/me").status_code == 401
    assert env.client.get("/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    h = login(env, "a@x.in")
    assert env.client.get("/me", headers=h).json()["has_pass"] is False
    env.clock.now += timedelta(days=2)  # past the 24h token lifetime
    assert env.client.get("/me", headers=h).status_code == 401


def test_otp_wrong_code_expiry_and_single_use(env):
    env.client.post("/members", json={"name": "A", "email": "a@x.in"})
    env.client.post("/auth/otp/request", json={"identifier": "a@x.in"})
    code = env.otp.last_code
    wrong = "000000" if code != "000000" else "111111"
    assert env.client.post("/auth/otp/verify", json={"identifier": "a@x.in", "code": wrong}).status_code == 401
    assert env.client.post("/auth/otp/verify", json={"identifier": "a@x.in", "code": code}).status_code == 200
    assert env.client.post("/auth/otp/verify", json={"identifier": "a@x.in", "code": code}).status_code == 401  # reuse
    env.client.post("/auth/otp/request", json={"identifier": "a@x.in"})
    code = env.otp.last_code
    env.clock.now += timedelta(seconds=settings.otp_ttl_seconds + 1)
    assert env.client.post("/auth/otp/verify", json={"identifier": "a@x.in", "code": code}).status_code == 401


def test_otp_locks_after_too_many_wrong_guesses(env):
    env.client.post("/members", json={"name": "A", "email": "a@x.in"})
    env.client.post("/auth/otp/request", json={"identifier": "a@x.in"})
    code = env.otp.last_code
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(settings.otp_max_attempts):
        env.client.post("/auth/otp/verify", json={"identifier": "a@x.in", "code": wrong})
    # even the right code no longer works
    assert env.client.post("/auth/otp/verify", json={"identifier": "a@x.in", "code": code}).status_code == 401


def test_otp_request_does_not_reveal_unknown_accounts(env):
    r = env.client.post("/auth/otp/request", json={"identifier": "ghost@x.in"})
    assert r.status_code == 202 and env.otp.sent == []


def test_login_by_phone_and_duplicate_member(env):
    env.client.post("/members", json={"name": "A", "email": "a@x.in", "phone": "+919800000001"})
    assert env.client.post("/members", json={"name": "B", "email": "a@x.in"}).status_code == 409
    env.client.post("/auth/otp/request", json={"identifier": "+919800000001"})
    assert env.otp.sent[-1][0] == "+919800000001"


# --- payments --------------------------------------------------------------------------------

def test_pass_requires_signed_webhook(env):
    h = login(env, "a@x.in")
    order = env.client.post("/me/pass/order", headers=h).json()
    body = {"event": "payment.captured", "order_id": order["order_id"], "payment_id": "p", "amount_paise":
            order["amount_paise"]}
    assert webhook(env, body, signature="deadbeef").status_code == 401
    assert env.client.post("/webhooks/payments", json=body).status_code == 401  # no signature at all
    assert env.client.get("/me", headers=h).json()["has_pass"] is False


def test_webhook_is_idempotent_and_checks_amount(env):
    h = login(env, "a@x.in")
    order = buy_pass(env, h)
    first = env.client.get("/me", headers=h).json()["pass_expires_at"]
    again = webhook(env, {"event": "payment.captured", "order_id": order["order_id"], "payment_id": "pay_1",
                          "amount_paise": order["amount_paise"]})
    assert again.json() == {"result": "duplicate"}
    assert env.client.get("/me", headers=h).json()["pass_expires_at"] == first  # not extended twice
    o2 = env.client.post("/me/pass/order", headers=h).json()
    bad = webhook(env, {"event": "payment.captured", "order_id": o2["order_id"], "payment_id": "p2", "amount_paise": 1})
    assert bad.json() == {"result": "amount_mismatch"}
    assert env.client.get("/me", headers=h).json()["pass_expires_at"] == first


def test_webhook_malformed_and_unrelated_events(env):
    raw = b"not json"
    r = env.client.post("/webhooks/payments", content=raw, headers={"X-Signature": sign(settings.webhook_secret, raw)})
    assert r.status_code == 400
    assert webhook(env, {"event": "refund.processed"}).json() == {"result": "ignored"}


# --- partner / admin auth --------------------------------------------------------------------

def test_partner_routes_require_valid_api_key(env):
    body = {"airline": "X", "flight_no": "X1", "origin": "BOM", "destination": "GOI", "departs_at": iso(5),
            "open_seats": 1}
    assert env.client.post("/partner/flights", json=body).status_code == 401
    assert env.client.post("/partner/flights", json=body, headers={"X-API-Key": "lsp_wrong"}).status_code == 401
    member = login(env, "a@x.in")  # a member's JWT is not a partner credential
    assert env.client.post("/partner/flights", json=body, headers=member).status_code == 401


def test_partner_cannot_touch_another_partners_flight(env):
    a, b = partner(env, "Air A"), partner(env, "Air B")
    fid = publish(env, a)
    r = env.client.post(f"/partner/flights/{fid}/seats", json={"open_seats": 0}, headers=b)
    assert r.status_code == 404
    assert env.client.post(f"/partner/flights/{fid}/seats", json={"open_seats": 1}, headers=a).status_code == 200


def test_partner_flight_requires_timezone_aware_departure(env):
    p = partner(env)
    r = env.client.post("/partner/flights", headers=p, json={
        "airline": "X", "flight_no": "X1", "origin": "BOM", "destination": "GOI",
        "departs_at": "2026-11-01T20:00:00", "open_seats": 1})
    assert r.status_code == 422


def test_admin_routes_locked_down(env, monkeypatch):
    assert env.client.post("/admin/partners", json={"name": "P"}).status_code == 401
    assert env.client.post("/admin/partners", json={"name": "P"}, headers={"X-Admin-Key": "no"}).status_code == 401
    monkeypatch.setattr(settings, "admin_api_key", "")
    assert env.client.post("/admin/partners", json={"name": "P"}, headers=ADMIN).status_code == 403


# --- booking, ownership ------------------------------------------------------------------------

def test_booking_needs_auth_pass_and_ownership(env):
    p = partner(env)
    fid = publish(env, p)
    assert env.client.post(f"/flights/{fid}/book").status_code == 401
    alice = login(env, "a@x.in")
    r = env.client.post(f"/flights/{fid}/book", headers=alice)
    assert r.status_code == 409 and "pass" in r.json()["detail"]
    buy_pass(env, alice)
    r = env.client.post(f"/flights/{fid}/book", headers=alice)
    assert r.status_code == 201 and r.json()["price_paise"] == 80_000 and r.json()["guaranteed"] is False
    bid = r.json()["id"]
    bob = login(env, "b@x.in", "Bob")
    assert env.client.post(f"/bookings/{bid}/cancel", headers=bob).status_code == 404  # not Bob's
    assert env.client.post(f"/bookings/{bid}/cancel", headers=alice).json() == {"status": "cancelled"}
    assert env.client.get("/me/bookings", headers=alice).json()[0]["status"] == "cancelled"


# --- the bump flow ---------------------------------------------------------------------------

def test_bump_refunds_notifies_and_grants_priority(env):
    p = partner(env)
    fid = publish(env, p, hours=10, seats=2)
    alice, bob = login(env, "a@x.in", "Alice"), login(env, "b@x.in", "Bob")
    for h in (alice, bob):
        buy_pass(env, h)
    env.client.post(f"/flights/{fid}/book", headers=alice)
    env.clock.now += timedelta(minutes=5)
    bob_booking = env.client.post(f"/flights/{fid}/book", headers=bob).json()["id"]

    r = env.client.post(f"/partner/flights/{fid}/seats", json={"open_seats": 1}, headers=p)
    assert r.json() == {"bumped_booking_ids": [bob_booking],
                        "refunds": [{"booking_id": bob_booking, "refund": "refunded"}]}
    assert [b["status"] for b in env.client.get("/me/bookings", headers=bob).json()] == ["bumped"]
    assert env.client.get("/me/bookings", headers=alice).json()[0]["status"] == "confirmed"
    assert len(env.notifier.bumps) == 1
    note = env.notifier.bumps[0]
    assert note["member_email"] == "b@x.in" and note["refund_ok"] is True and note["refund_paise"] == 80_000

    # Priority: a later flight on the same route has one seat; Bob's claim holds it against a newcomer.
    carol = login(env, "c@x.in", "Carol")
    buy_pass(env, carol)
    later = publish(env, p, hours=15, seats=1)
    assert env.client.get("/flights", params={"origin": "BOM"}).json() == []  # held seat is not for sale
    r = env.client.post(f"/flights/{later}/book", headers=carol)
    assert r.status_code == 409 and "bumped" in r.json()["detail"]
    r = env.client.post(f"/flights/{later}/book", headers=bob)
    assert r.status_code == 201
    # the claim is single-use
    again = publish(env, p, hours=16, seats=1)
    assert env.client.post(f"/flights/{again}/book", headers=carol).status_code == 201


def test_priority_hold_released_close_to_departure_and_on_expiry(env):
    p = partner(env)
    fid = publish(env, p, hours=10, seats=1)
    bob, carol = login(env, "b@x.in", "Bob"), login(env, "c@x.in", "Carol")
    buy_pass(env, bob)
    buy_pass(env, carol)
    env.client.post(f"/flights/{fid}/book", headers=bob)
    env.client.post(f"/partner/flights/{fid}/seats", json={"open_seats": 0}, headers=p)
    later = publish(env, p, hours=14, seats=1)
    assert env.client.post(f"/flights/{later}/book", headers=carol).status_code == 409
    env.clock.now += timedelta(hours=11)  # now 3h before departure: unclaimed seat goes back on sale
    assert env.client.post(f"/flights/{later}/book", headers=carol).status_code == 201


def test_bumped_member_exempt_from_booking_cap(env):
    p = partner(env)
    bob = login(env, "b@x.in", "Bob")
    buy_pass(env, bob)
    first = publish(env, p, hours=5, seats=1)
    env.client.post(f"/flights/{first}/book", headers=bob)
    for i in range(5):
        fid = publish(env, p, hours=20 + i, seats=1, dest="DEL")
        assert env.client.post(f"/flights/{fid}/book", headers=bob).status_code == 201
    capped = publish(env, p, hours=30, seats=1, dest="DEL")
    assert env.client.post(f"/flights/{capped}/book", headers=bob).status_code == 409  # at the cap of 6
    env.client.post(f"/partner/flights/{first}/seats", json={"open_seats": 0}, headers=p)  # bumped, cap frees one
    for_claim = publish(env, p, hours=12, seats=1, dest="GOI")
    assert env.client.post(f"/flights/{for_claim}/book", headers=bob).status_code == 201


def test_failed_refund_is_recorded_and_retried(env):
    p = partner(env)
    fid = publish(env, p, seats=1)
    bob = login(env, "b@x.in", "Bob")
    buy_pass(env, bob)
    env.client.post(f"/flights/{fid}/book", headers=bob)
    env.gateway.fail_refunds = True
    r = env.client.post(f"/partner/flights/{fid}/seats", json={"open_seats": 0}, headers=p)
    assert r.status_code == 200 and r.json()["refunds"][0]["refund"] == "failed"  # the bump still stands
    assert env.notifier.bumps[0]["refund_ok"] is False
    assert env.client.post("/admin/refunds/retry").status_code == 401
    env.gateway.fail_refunds = False
    assert env.client.post("/admin/refunds/retry", headers=ADMIN).json() == {"refunded": 1}
    assert env.client.post("/admin/refunds/retry", headers=ADMIN).json() == {"refunded": 0}


def test_notifier_failure_does_not_fail_seat_update(env):
    def boom(**_):
        raise RuntimeError("sms down")

    env.notifier.booking_bumped = boom
    p = partner(env)
    fid = publish(env, p, seats=1)
    bob = login(env, "b@x.in", "Bob")
    buy_pass(env, bob)
    env.client.post(f"/flights/{fid}/book", headers=bob)
    assert env.client.post(f"/partner/flights/{fid}/seats", json={"open_seats": 0}, headers=p).status_code == 200


# --- rate limiting, config -----------------------------------------------------------------

def test_auth_endpoints_are_rate_limited(env, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_auth", 3)
    limiter.reset()
    codes = [env.client.post("/auth/otp/request", json={"identifier": "a@x.in"}).status_code for _ in range(5)]
    assert codes == [202, 202, 202, 429, 429]


def test_global_rate_limit(env, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_default", 3)
    limiter.reset()
    codes = [env.client.get("/health").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_production_refuses_dev_configuration():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings(env="production").validate()
    Settings(env="staging").validate()  # dev stand-ins are fine outside production
    good = Settings(env="production", jwt_secret="x" * 40, webhook_secret="w", otp_sender="sms",
                    payment_gateway="razorpay")
    good.validate()
