from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    pass_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Flight(Base):
    """A partner-airline flight whose unsold seats are offered to pass holders."""

    __tablename__ = "flights"

    id: Mapped[int] = mapped_column(primary_key=True)
    airline: Mapped[str] = mapped_column(String(60))
    flight_no: Mapped[str] = mapped_column(String(12))
    origin: Mapped[str] = mapped_column(String(3), index=True)
    destination: Mapped[str] = mapped_column(String(3), index=True)
    departs_at: Mapped[datetime] = mapped_column(DateTime, index=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    flight: Mapped[Flight] = relationship()
