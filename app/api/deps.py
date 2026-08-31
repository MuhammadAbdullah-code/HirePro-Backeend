from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.database import Database

from app.core.security import decode_token
from app.db import get_db

DbSession = Annotated[Database, Depends(get_db)]
bearer = HTTPBearer(auto_error=False)


def current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict:
    error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if credentials is None:
        raise error
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise error from exc
    if db.revoked_tokens.find_one({"_id": payload.get("jti")}):
        raise error
    user = db.users.find_one({"_id": payload.get("sub")})
    if user is None or not user.get("is_active", True):
        raise error
    invalid_before = user.get("sessions_invalid_before")
    if invalid_before and payload.get("jti") != user.get("session_exempt_jti"):
        issued_at = payload.get("iat")
        if invalid_before.tzinfo is None:
            invalid_before = invalid_before.replace(tzinfo=UTC)
        cutoff = invalid_before.timestamp()
        if issued_at is None or float(issued_at) <= cutoff:
            raise error
    if user.get("is_admin"):
        db.admin_sessions.update_one({"_id": payload.get("jti")}, {"$set": {"last_seen_at": datetime.now(UTC)}})
    return user


def optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict | None:
    if credentials is None:
        return None
    return current_user(db, credentials)


def admin_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_role(user: dict, role: str) -> dict:
    if user.get("role", "customer") != role:
        raise HTTPException(status_code=403, detail=f"{role.capitalize()} access required")
    return user


def customer_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    return require_role(user, "customer")


def business_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    return require_role(user, "business")


CurrentUser = Annotated[dict, Depends(current_user)]
OptionalUser = Annotated[dict | None, Depends(optional_user)]
AdminUser = Annotated[dict, Depends(admin_user)]
CustomerUser = Annotated[dict, Depends(customer_user)]
BusinessUser = Annotated[dict, Depends(business_user)]
