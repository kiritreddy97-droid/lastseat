"""Orchestration across the DB and the outside world (payments, OTP, notifications).

services.py stays pure business rules; anything that talks to a provider lives here.
"""
import hmac
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services
from .config import settings
from .models import Booking, Member, OtpChallenge, Payment
from .notifications import Notifier
from .otp import OtpSender
from .payments import PaymentError, PaymentGateway
from .security import hash_otp, new_otp

log = logging.getLogger("lastseat.flows")


class OtpError(Exception):
    pass


# --- OTP login -------------------------------------------------------------------------------

def request_otp(db: Session, sender: OtpSender, identifier: str, now: datetime) -> None:
    """Issue a code if the identifier belongs to a member. Silent otherwise, so callers cannot probe for accounts."""
    member = db.scalar(select(Member).where((Member.email == identifier) | (Member.phone == identifier)))
    if member is None:
        return
    for old in db.scalars(select(OtpChallenge).where(OtpChallenge.member_id == member.id, ~OtpChallenge.consumed)):
        old.consumed = True
    code = new_otp()
    db.add(OtpChallenge(member_id=member.id, code_hash=hash_otp(member.id, code),
                        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds)))
    db.commit()
    sender.send(member.phone or member.email, code)


def verify_otp(db: Session, identifier: str, code: str, now: datetime) -> Member:
    member = db.scalar(select(Member).where((Member.email == identifier) | (Member.phone == identifier)))
    challenge = None
    if member:
        challenge = db.scalar(
            select(OtpChallenge).where(OtpChallenge.member_id == member.id, ~OtpChallenge.consumed)
            .order_by(OtpChallenge.id.desc())
        )
    if member is None or challenge is None or challenge.expires_at <= now:
        raise OtpError("invalid or expired code")
    challenge.attempts += 1
    if challenge.attempts > settings.otp_max_attempts:
        challenge.consumed = True
        db.commit()
        raise OtpError("invalid or expired code")
    if not hmac.compare_digest(challenge.code_hash, hash_otp(member.id, code)):
        db.commit()
        raise OtpError("invalid or expired code")
    challenge.consumed = True
    db.commit()
    return member


# --- pass purchase ---------------------------------------------------------------------------

def start_pass_purchase(db: Session, gateway: PaymentGateway, member: Member) -> Payment:
    order = gateway.create_order(services.PASS_PRICE_PAISE, receipt=f"pass-{member.id}")
    payment = Payment(member_id=member.id, kind="pass", status="created", amount_paise=order.amount_paise,
                      provider_order_id=order.order_id)
    db.add(payment)
    db.commit()
    return payment


def handle_payment_captured(db: Session, order_id: str, payment_id: str, amount_paise: int, now: datetime) -> str:
    """Webhook handler. Idempotent: gateways retry, and a retry must not extend the pass twice."""
    payment = db.scalar(select(Payment).where(Payment.provider_order_id == order_id))
    if payment is None:
        return "unknown_order"
    if payment.status != "created":
        return "duplicate"
    if payment.amount_paise != amount_paise:
        log.error("webhook amount mismatch", extra={"order_id": order_id, "expected": payment.amount_paise,
                                                    "got": amount_paise})
        return "amount_mismatch"
    payment.status = "captured"
    payment.provider_payment_id = payment_id
    services.buy_pass(db, db.get(Member, payment.member_id), now)
    db.commit()
    log.info("pass activated", extra={"member_id": payment.member_id, "order_id": order_id})
    return "ok"


# --- bookings, bumps and refunds ---------------------------------------------------------------

def book_and_charge(db: Session, gateway: PaymentGateway, member: Member, flight, now: datetime) -> Booking:
    booking = services.book(db, member, flight, now)
    try:
        charge = gateway.charge(booking.price_paise, member.id, idempotency_key=f"booking-{booking.id}")
    except PaymentError:
        db.rollback()
        raise
    db.add(Payment(member_id=member.id, booking_id=booking.id, kind="booking", status="captured",
                   amount_paise=booking.price_paise, provider_payment_id=charge.payment_id))
    db.commit()
    return booking


def refund_booking(db: Session, gateway: PaymentGateway, booking: Booking) -> Payment | None:
    """Refund a bumped booking once. Returns the refund row, or None if there was nothing to refund."""
    paid = db.scalar(select(Payment).where(Payment.booking_id == booking.id, Payment.kind == "booking",
                                           Payment.status == "captured"))
    if paid is None:
        return None
    refund = db.scalar(select(Payment).where(Payment.booking_id == booking.id, Payment.kind == "refund"))
    if refund is None:
        refund = Payment(member_id=booking.member_id, booking_id=booking.id, kind="refund", status="failed",
                         amount_paise=paid.amount_paise)
        db.add(refund)
    elif refund.status == "refunded":
        return refund
    try:
        result = gateway.refund(paid.provider_payment_id, paid.amount_paise, idempotency_key=f"refund-{booking.id}")
        refund.status, refund.provider_payment_id = "refunded", result.refund_id
        paid.status = "refunded"
    except PaymentError:
        refund.status = "failed"
        log.exception("refund failed; will need a retry", extra={"booking_id": booking.id})
    db.commit()
    return refund


def process_bumps(db: Session, gateway: PaymentGateway, notifier: Notifier, bumped: list[Booking]) -> list[dict]:
    """Refund and notify each bumped booking. The bump itself is already committed; money problems never undo it."""
    results = []
    for b in bumped:
        refund = refund_booking(db, gateway, b)
        member = db.get(Member, b.member_id)
        refund_ok = refund is not None and refund.status == "refunded"
        try:
            notifier.booking_bumped(member_email=member.email, member_phone=member.phone,
                                    flight_no=b.flight.flight_no, refund_paise=b.price_paise, refund_ok=refund_ok)
        except Exception:  # a down SMS provider must not fail the airline's seat update
            log.exception("bump notification failed", extra={"booking_id": b.id})
        log.info("booking bumped", extra={"booking_id": b.id, "member_id": b.member_id, "refunded": refund_ok})
        results.append({"booking_id": b.id, "refund": refund.status if refund else "none"})
    return results


def retry_failed_refunds(db: Session, gateway: PaymentGateway) -> int:
    failed = db.scalars(select(Payment).where(Payment.kind == "refund", Payment.status == "failed"))
    fixed = 0
    for r in list(failed):
        if refund_booking(db, gateway, db.get(Booking, r.booking_id)).status == "refunded":
            fixed += 1
    return fixed
