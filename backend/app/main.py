import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import flows, services
from .clock import utcnow
from .config import settings
from .db import get_db
from .logging_setup import configure_logging
from .models import Booking, Flight, Member, Partner
from .notifications import Notifier
from .otp import OtpSender
from .payments import PaymentError, PaymentGateway
from .providers import get_gateway, get_notifier, get_otp_sender
from .ratelimit import limiter
from .security import (
    create_token,
    current_member,
    current_partner,
    hash_api_key,
    new_api_key,
    require_admin,
)

log = logging.getLogger("lastseat.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()
    configure_logging(settings.log_level)
    # Schema is managed by Alembic (`alembic upgrade head`), not created here.
    yield


app = FastAPI(title="LastSeat India", lifespan=lifespan)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    start = time.perf_counter()
    if not limiter.allow(f"ip:{_client_ip(request)}", settings.rate_limit_default):
        response = JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
    else:
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": request_id, "path": request.url.path})
            response = JSONResponse({"detail": "internal error", "request_id": request_id}, status_code=500)
    response.headers["X-Request-ID"] = request_id
    log.info("request", extra={
        "request_id": request_id, "method": request.method, "path": request.url.path, "status": response.status_code,
        "duration_ms": round((time.perf_counter() - start) * 1000, 1), "ip": _client_ip(request),
    })
    return response


def auth_rate_limit(request: Request) -> None:
    if not limiter.allow(f"auth:{_client_ip(request)}", settings.rate_limit_auth):
        raise HTTPException(429, "too many attempts, try again in a minute", headers={"Retry-After": "60"})


# --- schemas -----------------------------------------------------------------------------------

class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    phone: str | None = Field(default=None, min_length=8, max_length=20)


class OtpRequestIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=200)  # email or phone


class OtpVerifyIn(OtpRequestIn):
    code: str = Field(min_length=6, max_length=6)


class FlightIn(BaseModel):
    airline: str = Field(max_length=60)
    flight_no: str = Field(max_length=12)
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departs_at: AwareDatetime  # must carry a UTC offset, e.g. +05:30
    open_seats: int = Field(ge=0)
    fare_paise: int = Field(default=50_000, ge=0)
    taxes_paise: int = Field(default=0, ge=0)


class SeatsIn(BaseModel):
    open_seats: int = Field(ge=0)


class PartnerIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def _get(db: Session, model, id_: int, **kw):
    obj = db.get(model, id_, **kw)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


# --- public ------------------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/flights")
def search_flights(origin: str | None = None, destination: str | None = None, db: Session = Depends(get_db),
                   now: datetime = Depends(utcnow)):
    return [
        {
            "id": f.id, "flight_no": f.flight_no, "origin": f.origin, "destination": f.destination,
            "departs_at": f.departs_at, "open_seats": services.available_seats(db, f, now),
            "price_paise": f.fare_paise + f.taxes_paise,
        }
        for f in services.search(db, now, origin, destination)
    ]


@app.post("/members", status_code=201, dependencies=[Depends(auth_rate_limit)])
def create_member(body: MemberIn, db: Session = Depends(get_db)):
    m = Member(**body.model_dump())
    db.add(m)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "email or phone already registered")
    return {"id": m.id}


@app.post("/auth/otp/request", status_code=202, dependencies=[Depends(auth_rate_limit)])
def otp_request(body: OtpRequestIn, db: Session = Depends(get_db), sender: OtpSender = Depends(get_otp_sender),
                now: datetime = Depends(utcnow)):
    flows.request_otp(db, sender, body.identifier, now)
    return {"detail": "if the account exists, a code has been sent"}  # same answer either way


@app.post("/auth/otp/verify", dependencies=[Depends(auth_rate_limit)])
def otp_verify(body: OtpVerifyIn, db: Session = Depends(get_db), now: datetime = Depends(utcnow)):
    try:
        member = flows.verify_otp(db, body.identifier, body.code, now)
    except flows.OtpError as e:
        raise HTTPException(401, str(e))
    return {"access_token": create_token(member.id, now), "token_type": "bearer"}


@app.post("/webhooks/payments")
async def payment_webhook(request: Request, db: Session = Depends(get_db),
                          gateway: PaymentGateway = Depends(get_gateway),
                          now: datetime = Depends(utcnow)):
    body = await request.body()
    if not gateway.verify_webhook(body, request.headers.get("x-signature", "")):
        raise HTTPException(401, "bad signature")
    try:
        event = json.loads(body)
        if event["event"] != "payment.captured":
            return {"result": "ignored"}
        outcome = flows.handle_payment_captured(
            db, event["order_id"], event["payment_id"], int(event["amount_paise"]), now
        )
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "malformed event")
    return {"result": outcome}


# --- members (JWT) -----------------------------------------------------------------------------

@app.get("/me")
def me(member: Member = Depends(current_member), now: datetime = Depends(utcnow)):
    return {"id": member.id, "name": member.name, "email": member.email, "pass_expires_at": member.pass_expires_at,
            "has_pass": services.has_pass(member, now)}


@app.post("/me/pass/order", status_code=201)
def pass_order(member: Member = Depends(current_member), db: Session = Depends(get_db),
               gateway: PaymentGateway = Depends(get_gateway)):
    """Starts checkout. The pass is only activated when the gateway's signed webhook confirms capture."""
    p = flows.start_pass_purchase(db, gateway, member)
    return {"order_id": p.provider_order_id, "amount_paise": p.amount_paise}


@app.post("/flights/{flight_id}/book", status_code=201)
def book_flight(flight_id: int, member: Member = Depends(current_member), db: Session = Depends(get_db),
                gateway: PaymentGateway = Depends(get_gateway), now: datetime = Depends(utcnow)):
    flight = _get(db, Flight, flight_id, with_for_update=True)  # serialise concurrent bookings of the last seat
    try:
        b = flows.book_and_charge(db, gateway, member, flight, now)
    except services.BookingError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    except PaymentError:
        raise HTTPException(402, "payment failed")
    return {"id": b.id, "price_paise": b.price_paise, "guaranteed": False}


@app.get("/me/bookings")
def my_bookings(member: Member = Depends(current_member), db: Session = Depends(get_db)):
    rows = db.scalars(select(Booking).where(Booking.member_id == member.id).order_by(Booking.id.desc()))
    return [{"id": b.id, "flight_id": b.flight_id, "flight_no": b.flight.flight_no, "status": b.status,
             "price_paise": b.price_paise} for b in rows]


@app.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, member: Member = Depends(current_member), db: Session = Depends(get_db)):
    booking = _get(db, Booking, booking_id)
    if booking.member_id != member.id:
        raise HTTPException(404, f"Booking {booking_id} not found")  # do not reveal other members' bookings
    try:
        b = services.cancel(db, booking)
    except services.BookingError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return {"status": b.status}


# --- airline partners (API key) ---------------------------------------------------------------

@app.post("/partner/flights", status_code=201)
def publish_flight(body: FlightIn, partner: Partner = Depends(current_partner), db: Session = Depends(get_db)):
    data = body.model_dump() | {"origin": body.origin.upper(), "destination": body.destination.upper()}
    f = Flight(**data, partner_id=partner.id)
    db.add(f)
    db.commit()
    return {"id": f.id}


@app.post("/partner/flights/{flight_id}/seats")
def update_seats(flight_id: int, body: SeatsIn, partner: Partner = Depends(current_partner),
                 db: Session = Depends(get_db), gateway: PaymentGateway = Depends(get_gateway),
                 notifier: Notifier = Depends(get_notifier), now: datetime = Depends(utcnow)):
    flight = _get(db, Flight, flight_id, with_for_update=True)
    if flight.partner_id != partner.id:
        raise HTTPException(404, f"Flight {flight_id} not found")  # partners only see their own flights
    bumped = services.reduce_open_seats(db, flight, body.open_seats, now)
    db.commit()  # the bump is final before any money or messages move
    results = flows.process_bumps(db, gateway, notifier, bumped)
    return {"bumped_booking_ids": [b.id for b in bumped], "refunds": results}


# --- admin (operator key) ---------------------------------------------------------------------

@app.post("/admin/partners", status_code=201, dependencies=[Depends(require_admin)])
def create_partner(body: PartnerIn, db: Session = Depends(get_db)):
    """Returns the API key exactly once; only its hash is stored."""
    key = new_api_key()
    p = Partner(name=body.name, api_key_hash=hash_api_key(key))
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "partner name already exists")
    return {"id": p.id, "api_key": key}


@app.post("/admin/refunds/retry", dependencies=[Depends(require_admin)])
def retry_refunds(db: Session = Depends(get_db), gateway: PaymentGateway = Depends(get_gateway)):
    return {"refunded": flows.retry_failed_refunds(db, gateway)}
