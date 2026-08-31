# ruff: noqa: B008

from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.api.deps import AdminUser, DbSession, bearer
from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password
from app.models import new_id, public, utc_now
from app.schemas.api import (
    BusinessOut,
    CommunicationSettings,
    FeatureControlSettings,
    GeneralAdminSettings,
    IntegrationSettings,
    LoginRequest,
    MarketplaceSettings,
    ModerationUpdate,
    PrivacySettings,
    ReviewOut,
    SecurityAdminSettings,
    SystemHealthSettings,
    TokenResponse,
    TrustSettings,
    VerificationUpdate,
)

router = APIRouter(prefix="/admin")
BearerCredentials = Annotated[HTTPAuthorizationCredentials, Depends(bearer)]


def admin_public(item: dict) -> dict:
    """Return an admin-safe document without authentication secrets."""
    result = public(item)
    for field in ("password_hash", "oauth_provider"):
        result.pop(field, None)
    return result


@router.post("/signin", response_model=TokenResponse)
def signin(payload: LoginRequest, db: DbSession) -> TokenResponse:
    """Sign in the single administrator configured for this deployment."""
    email = payload.email.strip().lower()
    configured_email = settings.admin_email.strip().lower()
    if not settings.admin_password or not (
        compare_digest(email, configured_email) and compare_digest(payload.password, settings.admin_password)
    ):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    now = utc_now()
    db.users.update_one(
        {"email": configured_email},
        {
            "$set": {
                "full_name": "HirePro Administrator",
                "password_hash": hash_password(settings.admin_password),
                "is_admin": True,
                "is_active": True,
                "role": "business",
                "updated_at": now,
            },
            "$setOnInsert": {
                "_id": new_id(),
                "email": configured_email,
                "oauth_provider": None,
                "created_at": now,
            },
        },
        upsert=True,
    )
    admin = db.users.find_one({"email": configured_email})
    token, jti, expires_at = create_access_token(str(admin["_id"]))
    db.admin_sessions.insert_one(
        {
            "_id": jti,
            "admin_id": admin["_id"],
            "created_at": now,
            "last_seen_at": now,
            "expires_at": expires_at,
            "revoked_at": None,
        }
    )
    return TokenResponse(access_token=token)


@router.post("/signout", status_code=204)
def signout(db: DbSession, _: AdminUser, credentials: BearerCredentials) -> None:
    """Revoke the administrator's current bearer token."""
    payload = decode_token(credentials.credentials)
    db.revoked_tokens.update_one(
        {"_id": payload["jti"]},
        {"$setOnInsert": {"expires_at": datetime.fromtimestamp(payload["exp"], tz=UTC)}},
        upsert=True,
    )


@router.get("/me")
def admin_me(user: AdminUser) -> dict:
    return public(user)


def sanitize_audit_value(value):
    if isinstance(value, dict):
        return {
            key: "********"
            if any(word in key.lower() for word in ("secret", "password", "token", "credential", "api_key"))
            else sanitize_audit_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_audit_value(item) for item in value]
    return value


def audit(
    db: DbSession,
    admin: dict,
    action: str,
    target_type: str,
    target_id: str,
    request: Request,
    metadata: dict | None = None,
    success: bool = True,
) -> None:
    db.audit_logs.insert_one(
        {
            "_id": str(__import__("uuid").uuid4()),
            "admin_id": admin["_id"],
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "metadata": sanitize_audit_value(metadata or {}),
            "success": success,
            "request_id": request.headers.get("x-request-id") or str(__import__("uuid").uuid4()),
            "ip_address": request.client.host if request.client else None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
    )


@router.get("/dashboard")
def dashboard(db: DbSession, _: AdminUser) -> dict:
    return {
        "stats": stats(db, _),
        "recent_registrations": [public(x) for x in db.users.find().sort("created_at", -1).limit(10)],
        "recent_businesses": [public(x) for x in db.businesses.find().sort("created_at", -1).limit(10)],
    }


@router.get("/action-queue")
def action_queue(db: DbSession, _: AdminUser) -> dict:
    return {
        "pending_verifications": db.verification_requests.count_documents({"status": "pending"}),
        "pending_reviews": db.reviews.count_documents({"is_approved": False}),
        "open_reports": db.reports.count_documents({"status": "open"}),
    }


def admin_resource(name: str, collection: str) -> None:
    @router.get(f"/{name}", name=f"admin_list_{name}")
    def listing(
        db: DbSession, _: AdminUser, q: str | None = None, limit: int = Query(20, le=100), offset: int = 0
    ) -> list[dict]:
        search_fields = {
            "users": ("full_name", "email", "phone"),
            "admins": ("full_name", "email"),
            "businesses": ("name", "city", "phone"),
        }.get(name, ("name", "title"))
        query = {"$or": [{field: {"$regex": q, "$options": "i"}} for field in search_fields]} if q else {}
        cursor = db[collection].find(query).sort("created_at", -1).skip(offset).limit(limit)
        return [admin_public(x) for x in cursor]

    @router.get(f"/{name}/{{item_id}}", name=f"admin_get_{name}")
    def get(item_id: str, db: DbSession, _: AdminUser) -> dict:
        item = db[collection].find_one({"_id": item_id})
        if item is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        return admin_public(item)

    @router.patch(f"/{name}/{{item_id}}", name=f"admin_update_{name}")
    def update(item_id: str, request: Request, payload: dict = Body(...), *, db: DbSession, admin: AdminUser) -> dict:
        item = db[collection].find_one_and_update(
            {"_id": item_id}, {"$set": {**payload, "updated_at": utc_now()}}, return_document=True
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        audit(db, admin, f"{name}_updated", name, item_id, request)
        return admin_public(item)

    @router.delete(f"/{name}/{{item_id}}", status_code=204, name=f"admin_delete_{name}")
    def remove(item_id: str, request: Request, db: DbSession, admin: AdminUser) -> None:
        db[collection].update_one({"_id": item_id}, {"$set": {"deleted_at": utc_now(), "is_active": False}})
        audit(db, admin, f"{name}_deleted", name, item_id, request)


for resource, collection in (
    ("users", "users"),
    ("businesses", "businesses"),
    ("reviews", "reviews"),
    ("reports", "reports"),
    ("requests", "customer_requests"),
    ("quotes", "provider_quotes"),
    ("contact-messages", "contact_messages"),
    ("categories", "categories"),
    ("locations", "locations"),
    ("admins", "users"),
):
    admin_resource(resource, collection)


@router.get("/audit-logs")
def audit_logs(
    db: DbSession,
    _: AdminUser,
    action: str | None = None,
    section: str | None = None,
    admin_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    query: dict = {}
    if action:
        query["action"] = {"$regex": action.strip(), "$options": "i"}
    if section:
        query["$or"] = [{"target_type": section}, {"target_id": section}]
    if admin_id:
        query["admin_id"] = admin_id
    if date_from or date_to:
        query["created_at"] = {}
        if date_from:
            query["created_at"]["$gte"] = date_from
        if date_to:
            query["created_at"]["$lte"] = date_to

    administrator_names: dict[str, str] = {}
    result = []
    cursor = db.audit_logs.find(query).sort("created_at", -1).skip(offset).limit(limit)
    for item in cursor:
        actor_id = str(item.get("admin_id", ""))
        if actor_id not in administrator_names:
            administrator = db.users.find_one({"_id": item.get("admin_id")}, {"full_name": 1}) or {}
            administrator_names[actor_id] = administrator.get("full_name", "Administrator")
        target_type = item.get("target_type")
        target_id = item.get("target_id")
        audit_section = target_id if target_type == "settings" and target_id != "platform" else target_type
        result.append(
            {
                **public(item),
                "admin_name": administrator_names[actor_id],
                "section": audit_section,
                "success": item.get("success", True),
            }
        )
    return result


@router.get("/audit-logs/{audit_id}")
def audit_log(audit_id: str, db: DbSession, _: AdminUser) -> dict:
    item = db.audit_logs.find_one({"_id": audit_id})
    if item is None:
        raise HTTPException(status_code=404, detail="Audit log not found")
    return public(item)


@router.post("/{resource}/{item_id}/{action}", tags=["admin-actions"])
def resource_action(
    resource: str,
    item_id: str,
    action: str,
    request: Request,
    payload: dict = Body(default={}),
    *,
    db: DbSession,
    admin: AdminUser,
    credentials: BearerCredentials,
) -> dict:
    if resource == "sessions" and item_id == "all" and action == "revoke":
        token_payload = decode_token(credentials.credentials)
        now = utc_now()
        db.users.update_many(
            {"is_admin": True},
            {"$set": {"sessions_invalid_before": now}, "$unset": {"session_exempt_jti": ""}},
        )
        db.users.update_one(
            {"_id": admin["_id"]},
            {"$set": {"session_exempt_jti": token_payload["jti"]}},
        )
        audit(db, admin, "admin_sessions_revoked", "security", "all", request)
        return {"status": "revoked", "current_session_preserved": True}
    collections = {
        "users": "users",
        "businesses": "businesses",
        "verifications": "verification_requests",
        "reviews": "reviews",
        "reports": "reports",
        "requests": "customer_requests",
        "quotes": "provider_quotes",
        "contact-messages": "contact_messages",
    }
    allowed = {
        "suspend",
        "activate",
        "approve",
        "reject",
        "request-information",
        "hide",
        "resolve",
        "dismiss",
        "escalate",
        "close",
        "reopen",
        "invalidate",
        "reply",
        "reset-password",
    }
    if resource not in collections or action not in allowed:
        raise HTTPException(status_code=404, detail="Admin action not found")
    values: dict = {"updated_at": utc_now()}
    if action == "suspend":
        values.update(is_active=False, status="suspended")
    elif action == "activate":
        values.update(is_active=True, status="active")
    elif action == "approve":
        values.update(status="approved", is_approved=True, reviewed_at=utc_now())
    elif action == "reject":
        values.update(status="rejected", is_approved=False, rejection_reason=payload.get("reason"))
    elif action == "request-information":
        values.update(status="information_requested", information_request=payload.get("reason"))
    elif action == "hide":
        values.update(status="hidden", is_approved=False)
    elif action in {"resolve", "dismiss", "escalate", "close", "reopen", "invalidate"}:
        values["status"] = action
    elif action == "reply":
        values["admin_reply"] = payload.get("message")
    elif action == "reset-password":
        from app.core.security import hash_password

        values["password_hash"] = hash_password(str(payload.get("new_password", "TemporaryPassword123!")))
    item = db[collections[resource]].find_one_and_update({"_id": item_id}, {"$set": values}, return_document=True)
    if item is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    audit(db, admin, f"{resource}_{action}", resource, item_id, request)
    return public(item)


AnalyticsRange = Literal["7d", "30d", "90d", "12m"]


def analytics_period(value: AnalyticsRange) -> tuple[datetime, int, int, str]:
    """Return period start, bucket count, days per bucket, and label format."""
    now = utc_now()
    if value == "7d":
        return now - timedelta(days=6), 7, 1, "%b %d"
    if value == "30d":
        return now - timedelta(days=29), 30, 1, "%b %d"
    if value == "90d":
        return now - timedelta(days=90), 13, 7, "%b %d"
    month_index = now.month - 1 - 11
    start = now.replace(year=now.year + month_index // 12, month=month_index % 12 + 1, day=1)
    return start, 12, 31, "%b %Y"


def growth_series(db: DbSession, value: AnalyticsRange) -> list[dict]:
    start, bucket_count, bucket_days, label_format = analytics_period(value)
    counts = [0] * bucket_count
    for user in db.users.find({"created_at": {"$gte": start}}, {"created_at": 1}):
        created_at = user.get("created_at")
        if not isinstance(created_at, datetime):
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if value == "12m":
            index = (created_at.year - start.year) * 12 + created_at.month - start.month
        else:
            index = (created_at - start).days // bucket_days
        if 0 <= index < bucket_count:
            counts[index] += 1
    points = []
    for index, count in enumerate(counts):
        if value == "12m":
            month_index = start.month - 1 + index
            bucket_date = start.replace(year=start.year + month_index // 12, month=month_index % 12 + 1, day=1)
        else:
            bucket_date = start + timedelta(days=index * bucket_days)
        points.append({"label": bucket_date.strftime(label_format), "value": count})
    return points


def top_businesses(db: DbSession, start: datetime, limit: int) -> list[dict]:
    results = []
    for business in db.businesses.find({"is_active": True}).sort("view_count", -1).limit(limit * 3):
        quote_count = db.provider_quotes.count_documents(
            {"provider_id": business.get("owner_id"), "created_at": {"$gte": start}, "deleted_at": None}
        )
        ratings = [
            row.get("rating", 0)
            for row in db.reviews.find(
                {"business_id": business["_id"], "is_approved": True, "created_at": {"$gte": start}},
                {"rating": 1},
            )
        ]
        results.append(
            {
                "id": str(business["_id"]),
                "name": business.get("name", "Unnamed business"),
                "views": business.get("view_count", 0),
                "quotes": quote_count,
                "rating": round(sum(ratings) / len(ratings), 1) if ratings else 0,
            }
        )
    results.sort(key=lambda item: (item["views"], item["quotes"], item["rating"]), reverse=True)
    return results[:limit]


@router.get("/analytics/{metric}")
def admin_analytics(
    metric: str,
    db: DbSession,
    _: AdminUser,
    range: AnalyticsRange = "30d",
    limit: int = Query(8, ge=1, le=100),
) -> dict | list[dict]:
    start, _, _, _ = analytics_period(range)
    if metric == "growth":
        return growth_series(db, range)
    if metric == "top-businesses":
        return top_businesses(db, start, limit)
    if metric == "conversion":
        period_filter = {"created_at": {"$gte": start}}
        return {
            "page_views": db.analytics_events.count_documents({**period_filter, "event_type": "page_view"}),
            "business_clicks": db.analytics_events.count_documents({**period_filter, "event_type": "business_click"}),
            "quote_requests": db.customer_requests.count_documents(period_filter),
        }
    raise HTTPException(status_code=404, detail="Metric not found")


@router.get("/settings")
def get_settings(db: DbSession, _: AdminUser) -> dict:
    item = db.platform_settings.find_one({"_id": "platform"}) or {}
    return platform_settings_response(db, item)


@router.patch("/settings")
def update_settings(payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    section = payload.get("section")
    values = payload.get("data")
    allowed_sections = {
        "general",
        "marketplace",
        "trust",
        "communications",
        "security",
        "integrations",
        "features",
        "health",
        "privacy",
    }
    if section not in allowed_sections or not isinstance(values, dict):
        raise HTTPException(status_code=422, detail="section and data are required")
    model = SETTINGS_SECTION_MODELS.get(str(section))
    if model is not None:
        try:
            values = model.model_validate(values).model_dump()
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if section == "integrations":
        stored = platform_settings_values(db.platform_settings.find_one({"_id": "platform"}) or {}).get(
            "integrations", {}
        )
        for provider, provider_values in values.items():
            if isinstance(stored.get(provider), dict) and "credentials" in stored[provider]:
                provider_values["credentials"] = stored[provider]["credentials"]
    now = utc_now()
    db.platform_settings.update_one(
        {"_id": "platform"},
        {
            "$set": {f"settings.{section}": values, "updated_at": now, "updated_by": admin["_id"]},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    db.admin_sessions.update_one({"_id": payload["jti"]}, {"$set": {"revoked_at": utc_now()}})
    audit(db, admin, "settings_updated", "settings", "platform", request)
    return platform_settings_response(db, db.platform_settings.find_one({"_id": "platform"}))


def platform_settings_values(item: dict) -> dict:
    values = dict(item.get("settings", {})) if isinstance(item.get("settings"), dict) else {}
    if "marketplace" not in values:
        legacy = item.get("marketplace")
        if item.get("section") == "marketplace" and isinstance(item.get("data"), dict):
            legacy = item["data"]
        if isinstance(legacy, dict):
            values["marketplace"] = legacy
    return values


def platform_settings_response(db: DbSession, item: dict) -> dict:
    updated_by = None
    if item.get("updated_by"):
        user = db.users.find_one({"_id": item["updated_by"]}, {"full_name": 1}) or {}
        updated_by = {"id": str(item["updated_by"]), "name": user.get("full_name", "Administrator")}
    return {
        "settings": platform_settings_values(item),
        "updated_at": item.get("updated_at"),
        "updated_by": updated_by,
    }


SETTINGS_SECTION_MODELS = {
    "general": GeneralAdminSettings,
    "marketplace": MarketplaceSettings,
    "trust": TrustSettings,
    "communications": CommunicationSettings,
    "security": SecurityAdminSettings,
    "integrations": IntegrationSettings,
    "features": FeatureControlSettings,
    "health": SystemHealthSettings,
    "privacy": PrivacySettings,
}


def section_settings_response(db: DbSession, item: dict, section: str, model: type) -> dict:
    values = platform_settings_values(item).get(section, {})
    data = model.model_validate(values).model_dump()
    response = platform_settings_response(db, item)
    return {"data": data, "updated_at": response["updated_at"], "updated_by": response["updated_by"]}


def persist_settings_section(
    db: DbSession, admin: dict, request: Request, section: str, data: dict
) -> dict:
    now = utc_now()
    existing = db.platform_settings.find_one({"_id": "platform"}) or {}
    previous = platform_settings_values(existing).get(section)
    db.platform_settings.update_one(
        {"_id": "platform"},
        {
            "$set": {f"settings.{section}": data, "updated_at": now, "updated_by": admin["_id"]},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    audit(
        db,
        admin,
        f"{section}_settings_updated",
        "settings",
        section,
        request,
        metadata={"previous": previous, "new": data},
    )
    return {
        "data": data,
        "updated_at": now,
        "updated_by": {"id": str(admin["_id"]), "name": admin.get("full_name", "Administrator")},
    }


def register_settings_section(section: str, model: type) -> None:
    @router.get(f"/settings/{section}", name=f"get_admin_{section}_settings")
    def get_section(db: DbSession, _: AdminUser) -> dict:
        item = db.platform_settings.find_one({"_id": "platform"}) or {}
        return section_settings_response(db, item, section, model)

    @router.patch(f"/settings/{section}", name=f"update_admin_{section}_settings")
    def update_section(
        payload: dict = Body(...), *, request: Request, db: DbSession, admin: AdminUser
    ) -> dict:
        try:
            data = model.model_validate(payload).model_dump()
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        if section == "integrations":
            stored = platform_settings_values(db.platform_settings.find_one({"_id": "platform"}) or {}).get(
                "integrations", {}
            )
            for provider, provider_values in data.items():
                if isinstance(stored.get(provider), dict) and "credentials" in stored[provider]:
                    provider_values["credentials"] = stored[provider]["credentials"]
        return persist_settings_section(db, admin, request, section, data)


for settings_section, settings_model in SETTINGS_SECTION_MODELS.items():
    if settings_section != "marketplace":
        register_settings_section(settings_section, settings_model)


@router.get("/settings/marketplace")
def get_marketplace_settings(db: DbSession, _: AdminUser) -> dict:
    item = db.platform_settings.find_one({"_id": "platform"}) or {}
    values = platform_settings_values(item).get("marketplace", {})
    data = MarketplaceSettings.model_validate(values).model_dump()
    response = platform_settings_response(db, item)
    return {"data": data, "updated_at": response["updated_at"], "updated_by": response["updated_by"]}


@router.patch("/settings/marketplace")
def update_marketplace_settings(
    payload: MarketplaceSettings, request: Request, db: DbSession, admin: AdminUser
) -> dict:
    return persist_settings_section(db, admin, request, "marketplace", payload.model_dump())


def current_system_health(db: DbSession) -> dict:
    checked_at = utc_now()
    try:
        db.command("ping")
        database_status = "operational"
    except Exception:
        database_status = "unavailable"
    settings_item = db.platform_settings.find_one({"_id": "platform"}) or {}
    integrations = section_settings_response(db, settings_item, "integrations", IntegrationSettings)["data"]
    services = {
        "main_api": "operational",
        "database": database_status,
        "authentication": "operational",
        "file_storage": "operational" if integrations["storage"]["connected"] else "not_configured",
        "email_provider": "operational" if integrations["email"]["connected"] else "not_configured",
        "background_jobs": "operational",
    }
    return {
        "status": "operational" if all(value == "operational" for value in services.values()) else "degraded",
        "services": services,
        "checked_at": checked_at,
    }


@router.get("/verification", response_model=list[BusinessOut])
def verification_queue(db: DbSession, _: AdminUser) -> list[dict]:
    return [public(x) for x in db.businesses.find({"is_verified": False, "is_active": True})]


@router.get("/verification/{business_id}")
def verification_detail(business_id: str, db: DbSession, _: AdminUser) -> dict:
    business = db.businesses.find_one({"_id": business_id})
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    verification = db.verification_requests.find_one(
        {"business_id": business_id}, sort=[("submitted_at", -1), ("created_at", -1)]
    )
    provider_id = (verification or {}).get("provider_id") or business.get("owner_id")
    provider = db.users.find_one({"_id": provider_id}) if provider_id else None
    provider_data = None
    if provider:
        provider_data = {
            "id": str(provider["_id"]),
            "name": provider.get("name", ""),
            "email": provider.get("email", ""),
            "phone": provider.get("phone", ""),
            "role": provider.get("role", "business"),
        }

    documents = []
    for index, value in enumerate((verification or {}).get("required_documents", [])):
        document_value = value if isinstance(value, dict) else {"type": str(value)}
        file_url = document_value.get("file_url") or document_value.get("url") or ""
        documents.append(
            {
                "id": str(document_value.get("id") or document_value.get("_id") or f"{business_id}-{index + 1}"),
                "type": document_value.get("type") or document_value.get("document_type") or "other",
                "file_url": file_url,
                "file_name": document_value.get("file_name") or document_value.get("name") or "",
                "status": document_value.get("status") or (verification or {}).get("status", "pending"),
            }
        )

    return {
        "business_id": business_id,
        "provider": provider_data,
        "status": (verification or {}).get("status", "not_submitted"),
        "submitted_at": (verification or {}).get("submitted_at"),
        "documents": documents,
    }


@router.patch("/verification/{business_id}", response_model=BusinessOut)
def verify_business(business_id: str, payload: VerificationUpdate, db: DbSession, _: AdminUser) -> dict:
    item = db.businesses.find_one_and_update(
        {"_id": business_id}, {"$set": {"is_verified": payload.verified, "updated_at": utc_now()}}, return_document=True
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return public(item)


@router.get("/stats")
def stats(db: DbSession, _: AdminUser) -> dict[str, int]:
    return {
        "users": db.users.count_documents({}),
        "businesses": db.businesses.count_documents({}),
        "reviews": db.reviews.count_documents({}),
        "quotes": db.customer_requests.count_documents({}),
        "open_contact_messages": db.contact_messages.count_documents({"status": "new"}),
    }


@router.get("/moderation/reviews", response_model=list[ReviewOut])
def moderation_queue(db: DbSession, _: AdminUser) -> list[dict]:
    return [public(x) for x in db.reviews.find({"is_approved": False}).sort("created_at", 1)]


@router.patch("/moderation/reviews/{review_id}", response_model=ReviewOut)
def moderate_review(review_id: str, payload: ModerationUpdate, db: DbSession, _: AdminUser) -> dict:
    item = db.reviews.find_one_and_update(
        {"_id": review_id}, {"$set": {"is_approved": payload.approved, "updated_at": utc_now()}}, return_document=True
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return public(item)
