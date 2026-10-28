from datetime import timedelta

import pytest

from app import services
from app.models import Flight, Member

from .conftest import NOW


def _member(db, email="a@x.in", with_pass=True):
    m = Member(name="A", email=email)
    db.add(m)
    db.flush()
    if with_pass:
        services.buy_pass(db, m, NOW)
    return m


def _flight(db, hours=20, seats=2, dest="GOI"):
    f = Flight(airline="Demo Air", flight_no="DA101", origin="BOM", destination=dest,
               departs_at=NOW + timedelta(hours=hours), open_seats=seats)
    db.add(f)
    db.flush()
    return f


def test_search_only_returns_window_and_open_seats(db):
    inside, outside, full = _flight(db, 20), _flight(db, 100), _flight(db, 10, seats=0)
    assert services.search(db, NOW) == [inside]
    assert outside not in services.search(db, NOW) and full not in services.search(db, NOW)


def test_book_decrements_seats_and_prices_with_taxes(db):
    f = _flight(db)
    f.taxes_paise = 30_000
    b = services.book(db, _member(db), f, NOW)
    assert b.price_paise == 80_000
    assert f.open_seats == 1


def test_pass_required(db):
    with pytest.raises(services.BookingError, match="pass"):
        services.book(db, _member(db, with_pass=False), _flight(db), NOW)


def test_outside_window_rejected(db):
    with pytest.raises(services.BookingError, match="window"):
        services.book(db, _member(db), _flight(db, hours=72), NOW)


def test_no_double_booking_same_flight(db):
    m, f = _member(db), _flight(db)
    services.book(db, m, f, NOW)
    with pytest.raises(services.BookingError, match="already"):
        services.book(db, m, f, NOW)


def test_cancel_returns_seat(db):
    f = _flight(db, seats=1)
    b = services.book(db, _member(db), f, NOW)
    services.cancel(db, b)
    assert f.open_seats == 1


def test_airline_pulls_seats_bumps_latest_first(db):
    f = _flight(db, seats=3)
    first = services.book(db, _member(db, "1@x.in"), f, NOW)
    second = services.book(db, _member(db, "2@x.in"), f, NOW + timedelta(minutes=1))
    third = services.book(db, _member(db, "3@x.in"), f, NOW + timedelta(minutes=2))
    first.created_at, second.created_at, third.created_at = NOW, NOW + timedelta(minutes=1), NOW + timedelta(minutes=2)
    bumped = services.reduce_open_seats(db, f, 1, NOW)
    assert [b.id for b in bumped] == [third.id, second.id]
    assert first.status == "confirmed" and f.open_seats == 0


def test_pass_renewal_extends_from_expiry(db):
    m = _member(db)
    first_expiry = m.pass_expires_at
    services.buy_pass(db, m, NOW + timedelta(days=10))
    assert m.pass_expires_at == first_expiry + timedelta(days=365)


def test_naive_datetimes_are_rejected_and_reads_are_utc(db):
    from datetime import datetime

    with pytest.raises(Exception, match="naive"):
        db.add(Flight(airline="A", flight_no="A1", origin="BOM", destination="GOI",
                      departs_at=datetime(2026, 11, 1, 12, 0), open_seats=1))
        db.flush()
    db.rollback()
    f = _flight(db)
    db.expire_all()
    assert f.departs_at.tzinfo is not None and f.departs_at == NOW + timedelta(hours=20)
