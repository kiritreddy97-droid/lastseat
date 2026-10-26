from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .clock import utcnow
from .db import Base, UTCDateTime


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    pass_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Partner(Base):
    """An airline integration. Authenticates with an API key; only its hash is stored."""

    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active: Mapped[bool] = mapped_column(default=True)


class Flight(Base):
    """A partner-airline flight whose unsold seats are offered to pass holders."""

    __tablename__ = "flights"

    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), index=True, nullable=True)
    airline: Mapped[str] = mapped_column(String(60))
    flight_no: Mapped[str] = mapped_column(String(12))
    origin: Mapped[str] = mapped_column(String(3), index=True)
    destination: Mapped[str] = mapped_column(String(3), index=True)
    departs_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    open_seats: Mapped[int] = mapped_column(Integer)  # seats the airline lets us sell
    fare_paise: Mapped[int] = mapped_column(Integer, default=50_000)  # Rs 500
    taxes_paise: Mapped[int] = mapped_column(Integer, default=0)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    flight_id: Mapped[int] = mapped_column(ForeignKey("flights.id"), index=True)
    price_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # confirmed|bumped|cancelled
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    flight: Mapped[Flight] = relationship()


class OtpChallenge(Base):
    """A pending login code. Only an HMAC of the code is stored."""

    __tablename__ = "otp_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(default=False)


class Payment(Base):
    """Every money movement: pass purchases, booking charges and refunds."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(10))  # pass | booking | refund
    status: Mapped[str] = mapped_column(String(10))  # created | captured | refunded | failed
    amount_paise: Mapped[int] = mapped_column(Integer)
    provider_order_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PriorityClaim(Base):
    """Granted when a member is bumped: first call on the next flight on the same route."""

    __tablename__ = "priority_claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    bumped_booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    origin: Mapped[str] = mapped_column(String(3))
    destination: Mapped[str] = mapped_column(String(3))
    after_departure: Mapped[datetime] = mapped_column(UTCDateTime)  # only later flights qualify
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
