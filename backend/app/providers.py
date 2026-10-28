from functools import lru_cache

from .config import settings
from .notifications import ConsoleNotifier, Notifier
from .otp import ConsoleOtpSender, OtpSender
from .payments import FakeGateway, PaymentGateway

# FastAPI dependencies. Swap implementations here (or via app.dependency_overrides in tests) once real
# SMS / payment providers exist.


@lru_cache
def get_otp_sender() -> OtpSender:
    if settings.otp_sender == "console":
        return ConsoleOtpSender()
    raise RuntimeError(f"unknown OTP_SENDER {settings.otp_sender!r}: no adapter implemented yet")


@lru_cache
def get_gateway() -> PaymentGateway:
    if settings.payment_gateway == "fake":
        return FakeGateway(settings.webhook_secret)
    raise RuntimeError(f"unknown PAYMENT_GATEWAY {settings.payment_gateway!r}: no adapter implemented yet")


@lru_cache
def get_notifier() -> Notifier:
    return ConsoleNotifier()
