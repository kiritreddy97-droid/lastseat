# LastSeat India: Product Requirements (MVP)

## MVP scope
- Pass purchase and renewal
- Airline-facing API to publish open seats and withdraw them
- 48-hour booking window search
- Booking with caps to prevent seat hoarding
- Bump handling: refund + notify latest bookings first
- Airline reservation-system integration (phase 2)

## Personas
- Flexible travellers: freelancers, students, remote workers
- Frequent leisure flyers on busy domestic routes (BOM-DEL, BOM-GOI, BLR-GOI)
- Airlines with predictable unsold inventory on certain routes

## Non-goals for MVP
- Native mobile apps (web first), advanced analytics, internationalisation.

## Acceptance
- Every rule in `backend/app/services.py` has tests in `backend/tests/`.
- `/health` responds and the API deploys from the Dockerfile.
- Pricing and legal pages are reviewed against `05-legal-compliance.md` before real users are onboarded.

## API
Run the backend and open `/docs` for the generated OpenAPI documentation.
