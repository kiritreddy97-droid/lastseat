import os
from dataclasses import dataclass, field

_DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-0123456789"
_DEV_WEBHOOK_SECRET = "dev-only-webhook-secret-change-me-0123456789"


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass
class Settings:
    """Read from the environment once at import. Tests may mutate the module-level `settings`."""

    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "dev"))  # dev | staging | production
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", _DEV_JWT_SECRET))
    jwt_ttl_minutes: int = field(default_factory=lambda: _int("JWT_TTL_MINUTES", 24 * 60))
    admin_api_key: str = field(default_factory=lambda: os.getenv("ADMIN_API_KEY", ""))  # empty disables /admin/*
    webhook_secret: str = field(default_factory=lambda: os.getenv("PAYMENT_WEBHOOK_SECRET", _DEV_WEBHOOK_SECRET))
    otp_sender: str = field(default_factory=lambda: os.getenv("OTP_SENDER", "console"))
    payment_gateway: str = field(default_factory=lambda: os.getenv("PAYMENT_GATEWAY", "fake"))
    otp_ttl_seconds: int = field(default_factory=lambda: _int("OTP_TTL_SECONDS", 300))
    otp_max_attempts: int = field(default_factory=lambda: _int("OTP_MAX_ATTEMPTS", 5))
    # Requests per minute per client IP. In-process only: see docs/03-architecture.md for multi-instance notes.
    rate_limit_default: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MIN", 120))
    rate_limit_auth: int = field(default_factory=lambda: _int("RATE_LIMIT_AUTH_PER_MIN", 5))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    def validate(self) -> None:
        """Refuse to boot a production instance with dev secrets or stand-in integrations."""
        if self.env != "production":
            return
        problems = []
        if self.jwt_secret == _DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be set to a random value of at least 32 characters")
        if self.webhook_secret == _DEV_WEBHOOK_SECRET:
            problems.append("PAYMENT_WEBHOOK_SECRET must be set")
        if self.otp_sender == "console":
            problems.append("OTP_SENDER=console would write login codes to the logs")
        if self.payment_gateway == "fake":
            problems.append("PAYMENT_GATEWAY=fake does not move real money")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


settings = Settings()
