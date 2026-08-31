from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pymongo.errors import DuplicateKeyError

from app.api.deps import CurrentUser, DbSession, bearer
from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.models import document, public
from app.schemas.api import (
    ForgotPasswordRequest,
    LoginRequest,
    OAuthRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserCreate,
    UserOut,
)

router = APIRouter(prefix="/auth")
BearerCredentials = Annotated[HTTPAuthorizationCredentials, Depends(bearer)]


def issue_token(user: dict, db: DbSession) -> TokenResponse:
    token, _, _ = create_access_token(str(user["_id"]))
    refresh = token_urlsafe(48)
    db.refresh_tokens.insert_one(
        document(
            token_hash=sha256(refresh.encode()).hexdigest(),
            user_id=user["_id"],
            expires_at=datetime.now(UTC) + timedelta(days=30),
            revoked_at=None,
        )
    )
    return TokenResponse(access_token=token, refresh_token=refresh)


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserCreate, db: DbSession) -> TokenResponse:
    email = payload.email.strip().lower()
    if email == settings.admin_email.strip().lower():
        raise HTTPException(status_code=409, detail="Email is reserved for the administrator")
    user = document(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        oauth_provider=None,
        is_active=True,
        is_admin=False,
        role=payload.role,
        phone=None,
        profile_image_url=None,
    )
    try:
        db.users.insert_one(user)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Email is already registered") from exc
    return issue_token(user, db)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.users.find_one({"email": payload.email.strip().lower()})
    if (
        user is None
        or user.get("password_hash") is None
        or not verify_password(payload.password, user["password_hash"])
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return issue_token(user, db)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    token_hash = sha256(payload.refresh_token.encode()).hexdigest()
    stored = db.refresh_tokens.find_one({"token_hash": token_hash, "revoked_at": None})
    if stored is None or stored["expires_at"] <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = db.users.find_one({"_id": stored["user_id"], "is_active": True})
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    db.refresh_tokens.update_one({"_id": stored["_id"]}, {"$set": {"revoked_at": datetime.now(UTC)}})
    return issue_token(user, db)


@router.post("/reset-password", status_code=204)
def reset_password(payload: ResetPasswordRequest, db: DbSession) -> None:
    stored = db.password_reset_tokens.find_one({"_id": payload.token})
    if stored is None or stored["expires_at"] <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    db.users.update_one({"_id": stored["user_id"]}, {"$set": {"password_hash": hash_password(payload.new_password)}})
    db.password_reset_tokens.delete_one({"_id": payload.token})
    db.refresh_tokens.update_many(
        {"user_id": stored["user_id"], "revoked_at": None}, {"$set": {"revoked_at": datetime.now(UTC)}}
    )


@router.post("/oauth", response_model=TokenResponse)
def oauth(_: OAuthRequest) -> TokenResponse:
    raise HTTPException(
        status_code=501, detail="OAuth provider verification must be configured before this endpoint is enabled"
    )


@router.post("/logout", status_code=204)
def logout(db: DbSession, _: CurrentUser, credentials: BearerCredentials) -> None:
    payload = decode_token(credentials.credentials)
    db.revoked_tokens.insert_one({"_id": payload["jti"], "expires_at": datetime.fromtimestamp(payload["exp"], tz=UTC)})


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> dict[str, str]:
    user = db.users.find_one({"email": payload.email.strip().lower()})
    if user:
        db.password_reset_tokens.insert_one(
            {"_id": token_urlsafe(32), "user_id": user["_id"], "expires_at": datetime.now(UTC) + timedelta(minutes=30)}
        )
    return {"message": "If the account exists, password reset instructions will be sent"}


@router.get("/me", response_model=UserOut)
def get_current_user(user: CurrentUser) -> dict:
    return public(user)
