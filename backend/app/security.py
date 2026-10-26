import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import utcnow
from .config import settings
from .db import get_db
from .models import Member, Partner

ALGORITHM = "HS256"
ISSUER = "lastseat"


def create_token(member_id: int, now: datetime) -> str:
    claims = {
        "sub": str(member_id), "role": "member", "iss": ISSUER,
        "iat": now, "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def hash_otp(member_id: int, code: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"{member_id}:{code}".encode(), hashlib.sha256).hexdigest()


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()  # keys are 256-bit random, so an unsalted hash is enough


def new_api_key() -> str:
    return "lsp_" + secrets.token_urlsafe(32)


def current_member(authorization: str | None = Header(default=None), db: Session = Depends(get_db),
                   now: datetime = Depends(utcnow)) -> Member:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    try:
        # Expiry is checked against our injectable clock below, not the library's wall clock.
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM], issuer=ISSUER,
                            options={"require": ["exp", "sub", "iss"], "verify_exp": False, "verify_iat": False})
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    if claims["exp"] <= now.timestamp():
        raise HTTPException(401, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    member = db.get(Member, int(claims["sub"])) if claims.get("role") == "member" else None
    if member is None:
        raise HTTPException(401, "invalid token")
    return member


def current_partner(x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)) -> Partner:
    partner = None
    if x_api_key:
        partner = db.scalar(select(Partner).where(Partner.api_key_hash == hash_api_key(x_api_key)))
    if partner is None or not partner.active:
        raise HTTPException(401, "invalid API key")
    return partner


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not settings.admin_api_key:
        raise HTTPException(403, "admin API disabled")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(401, "invalid admin key")
