import logging
from typing import Protocol

log = logging.getLogger("lastseat.notify")


class Notifier(Protocol):
    def booking_bumped(self, *, member_email: str, member_phone: str | None, flight_no: str, refund_paise: int,
                       refund_ok: bool) -> None:
        """Tell a member the airline sold their seat, that they were refunded, and that they have priority."""


class ConsoleNotifier:
    def booking_bumped(self, *, member_email: str, member_phone: str | None, flight_no: str, refund_paise: int,
                       refund_ok: bool) -> None:
        log.info(
            "notify: booking bumped",
            extra={"to": member_phone or member_email, "flight_no": flight_no, "refund_paise": refund_paise,
                   "refund_ok": refund_ok},
        )
