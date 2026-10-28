import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Protocol


class PaymentError(Exception):
    pass


@dataclass
class Order:
    order_id: str
    amount_paise: int


@dataclass
class Charge:
    payment_id: str


@dataclass
class Refund:
    refund_id: str


class PaymentGateway(Protocol):
    """What the app needs from a licensed gateway (e.g. Razorpay). Amounts are integer paise."""

    def create_order(self, amount_paise: int, receipt: str) -> Order:
        """Start a hosted checkout. Capture is confirmed later by a signed webhook."""

    def charge(self, amount_paise: int, member_id: int, idempotency_key: str) -> Charge:
        """Collect a booking fare from a member's saved mandate. Raise PaymentError on decline."""

    def refund(self, payment_id: str, amount_paise: int, idempotency_key: str) -> Refund:
        """Refund a captured payment. Must be idempotent on idempotency_key. Raise PaymentError on failure."""

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        """True only if `signature` authenticates `body` as coming from the gateway."""


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class FakeGateway:
    """In-memory stand-in: no network, no keys. Webhooks are HMAC-SHA256(body) in hex, like most gateways."""

    def __init__(self, webhook_secret: str) -> None:
        self._secret = webhook_secret
        self.refunds: dict[str, Refund] = {}
        self.fail_refunds = False  # tests flip this to exercise the retry path

    def create_order(self, amount_paise: int, receipt: str) -> Order:
        return Order(order_id=f"order_{secrets.token_hex(8)}", amount_paise=amount_paise)

    def charge(self, amount_paise: int, member_id: int, idempotency_key: str) -> Charge:
        return Charge(payment_id=f"pay_{secrets.token_hex(8)}")

    def refund(self, payment_id: str, amount_paise: int, idempotency_key: str) -> Refund:
        if self.fail_refunds:
            raise PaymentError("gateway unavailable")
        return self.refunds.setdefault(idempotency_key, Refund(refund_id=f"rfnd_{secrets.token_hex(8)}"))

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        return hmac.compare_digest(sign(self._secret, body), signature or "")
