"""
Auth workstream (G). Self-contained FastAPI APIRouter -- the integration
point for app/main.py is a single `app.include_router(auth.router)`.

Owns:
  - password hashing (passlib/bcrypt)
  - JWT access tokens (python-jose), signed with the JWT_SECRET env var
  - POST /auth/signup, POST /auth/login, GET /auth/me
  - get_current_user: the dependency every other route in the system uses
    to resolve the authenticated user and enforce per-user data isolation.
  - Optional TOTP-based 2FA (pyotp): POST /auth/2fa/setup, /auth/2fa/verify,
    /auth/2fa/disable, and a /auth/login flow that honors it.

TOTP 2FA design (follow-up to the original workstream):
  - Setup (`/auth/2fa/setup`) generates and *stores* a secret but does NOT
    flip `totp_enabled` -- that only happens once the user proves they can
    generate a valid code (`/auth/2fa/verify`), so an abandoned/incomplete
    QR scan never locks an account into requiring a code it can't produce.
  - Login: chose approach (a) from the two options on the table -- a single
    `POST /auth/login` call that takes an optional `totp_code` field.
      * No 2FA on the account -> logs in on email+password alone, exactly
        as before this change (fully backward compatible).
      * 2FA on, `totp_code` omitted -> returns `{"requires_2fa": true}`
        with NO token, after password has already been verified. The
        frontend re-prompts for a code and resubmits the same call with
        `totp_code` set.
      * 2FA on, `totp_code` provided -> verified via pyotp; wrong/expired
        code -> 401, correct code -> normal token response.
    Picked this over a two-step short-lived-intermediate-token flow because
    it keeps the auth surface to the one route/response shape every other
    workstream already codes against, with a single additive optional
    field -- no new token type or extra round-trip state to manage.
  - Disable (`/auth/2fa/disable`) requires re-confirmation via EITHER the
    account's current password OR a valid TOTP code (whichever is supplied
    in the request body; TOTP is checked first if both are present). Either
    is treated as sufficient proof of ownership -- this mirrors how most
    consumer apps (e.g. GitHub, Google) let you turn 2FA off with your
    password alone, without demanding the very factor you're disabling.

Depends on the storage workstream's documented contract:
  - storage.schemas.User
  - storage.json_store.get_user_by_email / save_user / load_users / save_all
  - storage.default_statuses.DEFAULT_STATUSES
These modules are being built in parallel; until they land, the imports
below will fail -- that's expected (see summary). The code is structured
against the contract documented in the plan, not against a local stub.
"""
import os
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional

import pyotp
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from storage import json_store
from storage.default_statuses import DEFAULT_STATUSES

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DEV_FALLBACK_SECRET = "dev-insecure-secret-change-me"
JWT_SECRET = os.getenv("JWT_SECRET", _DEV_FALLBACK_SECRET)
if JWT_SECRET == _DEV_FALLBACK_SECRET:
    warnings.warn(
        "JWT_SECRET is not set; falling back to an insecure development "
        "secret. Set JWT_SECRET in the environment (see .env.example) "
        "before deploying.",
        stacklevel=2,
    )

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24 * 7)))  # 7 days

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer_scheme = HTTPBearer()

TOTP_ISSUER_NAME = "Smart Job Search Engine"

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decodes and validates a JWT; raises HTTPException(401) on failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Internal user lookup helpers
# ---------------------------------------------------------------------------

def _get_user_by_id(user_id: str) -> Optional[dict]:
    """Looks up a user by user_id out of the global account list.

    storage.json_store's documented contract only exposes get_user_by_email
    for lookups (plus load_users for the full list) -- there's no
    get_user_by_id in the contract, so we scan load_users() here rather than
    adding a new function to a module another workstream owns.
    """
    for user in json_store.load_users():
        if user.get("user_id") == user_id:
            return user
    return None


def _public_user(user: dict) -> dict:
    """Strips password_hash before a user record goes into any response."""
    return {k: v for k, v in user.items() if k != "password_hash"}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: str
    password: str
    totp_code: Optional[str] = None  # only required when the account has totp_enabled=True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class LoginResponse(BaseModel):
    """Response shape for POST /auth/login.

    Either `requires_2fa=True` with no token (password was correct but the
    account needs a totp_code the caller didn't send), or a normal token
    response. See the module docstring for the full login/2FA decision.
    """
    requires_2fa: bool = False
    access_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[dict] = None


class TOTPSetupResponse(BaseModel):
    secret: str  # manual-entry fallback, in case the user can't scan a QR code
    provisioning_uri: str  # render this as a QR code client-side


class TOTPVerifyRequest(BaseModel):
    code: str


class TOTPDisableRequest(BaseModel):
    password: Optional[str] = None
    totp_code: Optional[str] = None


# ---------------------------------------------------------------------------
# get_current_user -- the dependency every other route depends on
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency: decodes the JWT from the `Authorization: Bearer
    <token>` header and resolves it to the current user record.

    Usage in other routers:
        from app.auth import get_current_user
        @router.get("/something")
        async def handler(current_user: dict = Depends(get_current_user)):
            user_id = current_user["user_id"]
            ...

    Returns the user dict (storage.schemas.User shape) with password_hash
    stripped. Raises HTTPException(401) if the token is missing/invalid/
    expired, or if it decodes fine but no matching user exists (e.g. the
    account was deleted).
    """
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = _get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _public_user(user)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/signup", response_model=TokenResponse)
async def signup(body: SignupRequest):
    email = body.email.strip().lower()

    if json_store.get_user_by_email(email) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists",
        )

    user_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    user = {
        "user_id": user_id,
        "email": email,
        "password_hash": hash_password(body.password),
        "created_at": now_iso,
        "notify_email": email,
        "digest_enabled": True,
        "totp_secret": None,
        "totp_enabled": False,
    }
    json_store.save_user(user)

    # Seed this user's tracker_statuses.json with the default status pipeline.
    tracker_statuses = [
        {
            "status_id": str(uuid.uuid4()),
            "user_id": user_id,
            "label": default_status["label"],
            "color": default_status["color"],
            "order": index,
        }
        for index, default_status in enumerate(DEFAULT_STATUSES)
    ]
    json_store.save_all(user_id, "tracker_statuses", tracker_statuses)

    token = create_access_token(user_id, email)
    return TokenResponse(access_token=token, user=_public_user(user))


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    email = body.email.strip().lower()
    user = json_store.get_user_by_email(email)

    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # See module docstring ("TOTP 2FA design") for why this is a single
    # endpoint with an optional totp_code rather than a two-step flow.
    if user.get("totp_enabled"):
        if not body.totp_code:
            return LoginResponse(requires_2fa=True)
        totp = pyotp.totp.TOTP(user["totp_secret"])
        if not totp.verify(body.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired two-factor code",
            )

    token = create_access_token(user["user_id"], user["email"])
    return LoginResponse(access_token=token, user=_public_user(user))


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# Two-factor authentication (TOTP, via pyotp)
# ---------------------------------------------------------------------------

@router.post("/2fa/setup", response_model=TOTPSetupResponse)
async def setup_2fa(current_user: dict = Depends(get_current_user)):
    """Starts (or restarts) 2FA setup: generates a new secret and stores it,
    but deliberately does NOT set totp_enabled -- that only happens in
    /2fa/verify, once the user proves they can actually produce a valid
    code from it. Calling this again before verifying just issues a fresh
    secret (e.g. if the user abandoned a previous QR scan)."""
    user = _get_user_by_id(current_user["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    secret = pyotp.random_base32()
    user["totp_secret"] = secret
    user["totp_enabled"] = False
    json_store.save_user(user)

    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user["email"], issuer_name=TOTP_ISSUER_NAME
    )
    return TOTPSetupResponse(secret=secret, provisioning_uri=provisioning_uri)


@router.post("/2fa/verify")
async def verify_2fa(body: TOTPVerifyRequest, current_user: dict = Depends(get_current_user)):
    """Confirms a code generated from the secret issued by /2fa/setup, and
    is the step that actually flips totp_enabled=True."""
    user = _get_user_by_id(current_user["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.get("totp_secret"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA setup has not been started; call /auth/2fa/setup first",
        )

    totp = pyotp.totp.TOTP(user["totp_secret"])
    if not totp.verify(body.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code")

    user["totp_enabled"] = True
    json_store.save_user(user)
    return {"totp_enabled": True}


@router.post("/2fa/disable")
async def disable_2fa(body: TOTPDisableRequest, current_user: dict = Depends(get_current_user)):
    """Turns 2FA off. Requires re-confirmation via EITHER the account's
    current password OR a valid TOTP code (TOTP is checked first if both
    are supplied) -- see module docstring for why password-only is an
    accepted path here."""
    user = _get_user_by_id(current_user["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.get("totp_enabled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not enabled on this account",
        )

    verified = False
    if body.totp_code:
        totp = pyotp.totp.TOTP(user["totp_secret"])
        verified = totp.verify(body.totp_code)
    elif body.password:
        verified = verify_password(body.password, user["password_hash"])

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Re-confirmation failed: provide your current password or a valid 2FA code",
        )

    user["totp_enabled"] = False
    user["totp_secret"] = None
    json_store.save_user(user)
    return {"totp_enabled": False}
