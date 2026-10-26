from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import services
from .db import Base, engine, get_db
from .models import Booking, Flight, Member


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="LastSeat India", lifespan=lifespan)


class MemberIn(BaseModel):
    name: str
    email: str


class FlightIn(BaseModel):
    airline: str
    flight_no: str
    origin: str
    destination: str
    departs_at: datetime
    open_seats: int
    fare_paise: int = 50_000
    taxes_paise: int = 0


class SeatsIn(BaseModel):
    open_seats: int


def _get(db: Session, model, id_: int):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/members", status_code=201)
def create_member(body: MemberIn, db: Session = Depends(get_db)):
    m = Member(**body.model_dump())
    db.add(m)
    db.commit()
    return {"id": m.id}


@app.post("/members/{member_id}/pass")
def purchase_pass(member_id: int, db: Session = Depends(get_db)):
    # Payment capture (Razorpay) happens before this in production.
    m = services.buy_pass(db, _get(db, Member, member_id), datetime.utcnow())
    db.commit()
    return {"pass_expires_at": m.pass_expires_at}


@app.post("/partner/flights", status_code=201)
def publish_flight(body: FlightIn, db: Session = Depends(get_db)):
    # Airline-facing (API key auth in production): publishes seats they will let us sell.
    f = Flight(**body.model_dump(), origin=body.origin.upper(), destination=body.destination.upper())
    db.add(f)
    db.commit()
    return {"id": f.id}


@app.post("/partner/flights/{flight_id}/seats")
def update_seats(flight_id: int, body: SeatsIn, db: Session = Depends(get_db)):
    bumped = services.reduce_open_seats(db, _get(db, Flight, flight_id), body.open_seats)
    db.commit()
    return {"bumped_booking_ids": [b.id for b in bumped]}


@app.get("/flights")
def search_flights(origin: str | None = None, destination: str | None = None, db: Session = Depends(get_db)):
    return [
        {
            "id": f.id, "flight_no": f.flight_no, "origin": f.origin, "destination": f.destination,
            "departs_at": f.departs_at, "open_seats": f.open_seats, "price_paise": f.fare_paise + f.taxes_paise,
        }
        for f in services.search(db, datetime.utcnow(), origin, destination)
    ]


@app.post("/members/{member_id}/bookings/{flight_id}", status_code=201)
def book_flight(member_id: int, flight_id: int, db: Session = Depends(get_db)):
    try:
        b = services.book(db, _get(db, Member, member_id), _get(db, Flight, flight_id), datetime.utcnow())
    except services.BookingError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return {"id": b.id, "price_paise": b.price_paise, "guaranteed": False}


@app.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    try:
        b = services.cancel(db, _get(db, Booking, booking_id))
    except services.BookingError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return {"status": b.status}
