from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Booking, Flight, Member

PASS_PRICE_PAISE = 25_000 * 100  # Rs 25,000 / year
BOOKING_WINDOW = timedelta(hours=48)  # seats open to the pass only close to departure
MAX_ACTIVE_BOOKINGS = 6  # keeps one member from draining every empty seat


class BookingError(Exception):
    pass


def buy_pass(db: Session, member: Member, now: datetime) -> Member:
    start = member.pass_expires_at if member.pass_expires_at and member.pass_expires_at > now else now
    member.pass_expires_at = start + timedelta(days=365)
    db.flush()
    return member


def has_pass(member: Member, now: datetime) -> bool:
    return member.pass_expires_at is not None and member.pass_expires_at > now


def search(db: Session, now: datetime, origin: str | None = None, destination: str | None = None) -> list[Flight]:
    q = select(Flight).where(
        Flight.open_seats > 0, Flight.departs_at > now, Flight.departs_at <= now + BOOKING_WINDOW
    )
    if origin:
        q = q.where(Flight.origin == origin.upper())
    if destination:
        q = q.where(Flight.destination == destination.upper())
    return list(db.scalars(q.order_by(Flight.departs_at)))


def _active_count(db: Session, member_id: int, now: datetime) -> int:
    return db.scalar(
        select(func.count(Booking.id))
        .join(Flight)
        .where(Booking.member_id == member_id, Booking.status == "confirmed", Flight.departs_at > now)
    )


def book(db: Session, member: Member, flight: Flight, now: datetime) -> Booking:
    if not has_pass(member, now):
        raise BookingError("active pass required")
    if flight.departs_at <= now or flight.departs_at > now + BOOKING_WINDOW:
        raise BookingError("flight is outside the booking window")
    if flight.open_seats < 1:
        raise BookingError("no seats left")
    if _active_count(db, member.id, now) >= MAX_ACTIVE_BOOKINGS:
        raise BookingError("active booking limit reached")
    already = db.scalar(
        select(Booking.id).where(
            Booking.member_id == member.id, Booking.flight_id == flight.id, Booking.status == "confirmed"
        )
    )
    if already:
        raise BookingError("already booked on this flight")
    flight.open_seats -= 1
    booking = Booking(member_id=member.id, flight_id=flight.id, price_paise=flight.fare_paise + flight.taxes_paise)
    db.add(booking)
    db.flush()
    return booking


def cancel(db: Session, booking: Booking) -> Booking:
    if booking.status != "confirmed":
        raise BookingError(f"booking is {booking.status}")
    booking.status = "cancelled"
    booking.flight.open_seats += 1
    db.flush()
    return booking


def reduce_open_seats(db: Session, flight: Flight, new_open: int) -> list[Booking]:
    """The airline sold the seats after all (seats are unguaranteed).

    Bumps the most recent bookings first and returns them so the caller can refund
    and notify. Bumped members keep priority access to the next eligible flight.
    """
    confirmed = list(
        db.scalars(
            select(Booking)
            .where(Booking.flight_id == flight.id, Booking.status == "confirmed")
            .order_by(Booking.created_at.desc(), Booking.id.desc())
        )
    )
    capacity_used = len(confirmed)
    bumped: list[Booking] = []
    while capacity_used > new_open and confirmed:
        b = confirmed.pop(0)
        b.status = "bumped"
        bumped.append(b)
        capacity_used -= 1
    flight.open_seats = max(new_open - capacity_used, 0)
    db.flush()
    return bumped
