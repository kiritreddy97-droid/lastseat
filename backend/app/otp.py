import logging
from typing import Protocol

log = logging.getLogger("lastseat.otp")


class OtpSender(Protocol):
    def send(self, destination: str, code: str) -> None:
        """Deliver a login code (SMS/email). Raise on failure."""


class ConsoleOtpSender:
    """Dev only: writes the code to the log. Refused in production by Settings.validate()."""

    def send(self, destination: str, code: str) -> None:
        log.warning("otp issued (console sender, dev only)", extra={"destination": destination, "code": code})
