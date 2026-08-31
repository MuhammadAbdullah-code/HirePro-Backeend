# ruff: noqa: B008

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from app.api.deps import AdminUser, DbSession
from app.api.routes.admin import (
    SETTINGS_SECTION_MODELS,
    BearerCredentials,
    audit,
    current_system_health,
    persist_settings_section,
    platform_settings_values,
    section_settings_response,
)
from app.core.config import settings
from app.core.security import decode_token
from app.models import document, public, utc_now
from app.schemas.api import IntegrationStatus, PrivacySettings, TrustSettings

router = APIRouter(prefix="/admin", tags=["admin-settings"])
INTEGRATION_PROVIDERS = {"email", "storage", "maps", "payments", "analytics", "sms"}
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/x-icon": ".ico"}
DEFAULT_DOCUMENTS = ["Identity document", "Business registration"]
DEFAULT_PERMISSIONS = [
    "settings.read",
    "settings.write",
    "users.manage",
    "businesses.manage",
    "moderation.manage",
    "audit.read",
]


def settings_item(db: DbSession) -> dict:
    return db.platform_settings.find_one({"_id": "platform"}) or {}


def integration_values(db: DbSession) -> dict:
    model = SETTINGS_SECTION_MODELS["integrations"]
    return section_settings_response(db, settings_item(db), "integrations", model)["data"]


def mask_secrets(value: dict) -> dict:
    result = dict(value)
    for key in list(result):
        if any(word in key.lower() for word in ("secret", "password", "token", "api_key")):
            result[key] = "********" if result[key] else ""
    return result


async def save_brand_asset(kind: str, file: UploadFile, db: DbSession, admin: dict, request: Request) -> dict:
    suffix = IMAGE_TYPES.get(file.content_type or "")
    if suffix is None or (kind == "favicon" and suffix not in {".png", ".ico"}):
        raise HTTPException(status_code=415, detail="Unsupported image type")
    content = await file.read(settings.maximum_upload_bytes + 1)
    if len(content) > settings.maximum_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the configured size limit")
    directory = Path(settings.upload_directory).resolve() / "settings"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{kind}-{uuid4().hex}{suffix}"
    (directory / filename).write_bytes(content)
    url = f"/uploads/settings/{filename}"
    now = utc_now()
    db.platform_settings.update_one(
        {"_id": "platform"},
        {"$set": {f"settings.general.{kind}_url": url, "updated_at": now, "updated_by": admin["_id"]}},
        upsert=True,
    )
    audit(db, admin, f"{kind}_updated", "settings", "general", request)
    return {"url": url, "content_type": file.content_type, "size": len(content), "updated_at": now}


@router.post("/settings/general/logo", status_code=201)
async def upload_logo(request: Request, db: DbSession, admin: AdminUser, file: UploadFile = File(...)) -> dict:
    return await save_brand_asset("logo", file, db, admin, request)


@router.post("/settings/general/favicon", status_code=201)
async def upload_favicon(
    request: Request, db: DbSession, admin: AdminUser, file: UploadFile = File(...)
) -> dict:
    return await save_brand_asset("favicon", file, db, admin, request)


@router.get("/settings/general/options")
def general_options(_: AdminUser) -> dict:
    return {
        "countries": [{"code": "PK", "name": "Pakistan"}, {"code": "US", "name": "United States"}],
        "currencies": [{"code": "PKR", "name": "Pakistani Rupee"}, {"code": "USD", "name": "US Dollar"}],
        "timezones": ["Asia/Karachi", "UTC", "America/New_York", "Europe/London"],
        "languages": [{"code": "en", "name": "English"}, {"code": "ur", "name": "Urdu"}],
    }


@router.post("/settings/marketplace/impact-preview")
def marketplace_impact_preview(payload: dict, db: DbSession, _: AdminUser) -> dict:
    current = platform_settings_values(settings_item(db)).get("marketplace", {})
    candidate = SETTINGS_SECTION_MODELS["marketplace"].model_validate({**current, **payload}).model_dump()
    warnings = []
    if candidate["quote_expiry_days"] > candidate["request_expiry_days"]:
        warnings.append("Quote expiry exceeds request expiry")
    if not candidate["provider_registration"]:
        warnings.append("New provider registration will be disabled")
    return {
        "valid": not warnings,
        "warnings": warnings,
        "affected": {
            "providers": db.users.count_documents({"role": "business", "is_active": True}),
            "open_requests": db.customer_requests.count_documents({"status": {"$in": ["open", "receiving_quotes"]}}),
        },
        "effective_settings": candidate,
    }


@router.get("/settings/trust-safety")
def get_trust_safety(db: DbSession, _: AdminUser) -> dict:
    return section_settings_response(db, settings_item(db), "trust", TrustSettings)


@router.patch("/settings/trust-safety")
def update_trust_safety(payload: TrustSettings, request: Request, db: DbSession, admin: AdminUser) -> dict:
    return persist_settings_section(db, admin, request, "trust", payload.model_dump())


@router.post("/settings/trust-safety/impact-preview")
def trust_impact_preview(payload: dict, db: DbSession, _: AdminUser) -> dict:
    current = platform_settings_values(settings_item(db)).get("trust", {})
    candidate = TrustSettings.model_validate({**current, **payload}).model_dump()
    high_risk = candidate["verification_mode"] == "automatic" or candidate["review_moderation"] == "automatic"
    return {
        "high_risk": high_risk,
        "requires_confirmation": high_risk,
        "affected": {
            "active_businesses": db.businesses.count_documents({"is_active": True}),
            "approved_reviews": db.reviews.count_documents({"is_approved": True}),
        },
        "effective_settings": candidate,
    }


@router.get("/verification-documents")
def verification_documents(db: DbSession, _: AdminUser) -> list[dict]:
    rows = list(db.verification_document_types.find().sort("name", 1))
    if not rows:
        rows = [{"_id": name.lower().replace(" ", "-"), "name": name, "required": True} for name in DEFAULT_DOCUMENTS]
    return [public(row) for row in rows]


@router.get("/blocked-keywords")
def blocked_keywords(db: DbSession, _: AdminUser) -> list[dict]:
    return [public(row) for row in db.blocked_keywords.find().sort("value", 1)]


@router.post("/blocked-keywords", status_code=201)
def create_blocked_keyword(payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    value = str(payload.get("value", "")).strip().lower()
    if not value or len(value) > 100:
        raise HTTPException(status_code=422, detail="A keyword of 1-100 characters is required")
    if db.blocked_keywords.find_one({"value": value}):
        raise HTTPException(status_code=409, detail="Keyword already exists")
    item = document(value=value, created_by=admin["_id"])
    db.blocked_keywords.insert_one(item)
    audit(db, admin, "blocked_keyword_created", "trust", item["_id"], request)
    return public(item)


@router.delete("/blocked-keywords/{keyword_id}", status_code=204)
def delete_blocked_keyword(keyword_id: str, request: Request, db: DbSession, admin: AdminUser) -> None:
    if db.blocked_keywords.delete_one({"_id": keyword_id}).deleted_count == 0:
        raise HTTPException(status_code=404, detail="Keyword not found")
    audit(db, admin, "blocked_keyword_deleted", "trust", keyword_id, request)


@router.post("/communications/test-email", status_code=202)
def test_email(payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    recipient = str(payload.get("recipient", "")).strip()
    if "@" not in recipient:
        raise HTTPException(status_code=422, detail="A valid recipient is required")
    job = document(type="test_email", recipient=recipient, status="queued", requested_by=admin["_id"])
    db.admin_jobs.insert_one(job)
    audit(db, admin, "test_email_requested", "communications", job["_id"], request)
    return public(job)


def default_templates() -> list[dict]:
    return [
        {"_id": "welcome", "name": "Welcome", "subject": "Welcome to HirePro", "body": "Welcome, {{name}}!"},
        {
            "_id": "quote-received",
            "name": "Quote received",
            "subject": "You received a quote",
            "body": "A new quote is ready.",
        },
    ]


def template_or_default(db: DbSession, template_id: str) -> dict | None:
    stored = db.communication_templates.find_one({"_id": template_id})
    if stored:
        return stored
    return next((item for item in default_templates() if item["_id"] == template_id), None)


@router.get("/communication-templates")
def communication_templates(db: DbSession, _: AdminUser) -> list[dict]:
    stored = {item["_id"]: item for item in db.communication_templates.find()}
    for item in default_templates():
        stored.setdefault(item["_id"], item)
    return [public(item) for item in stored.values()]


@router.get("/communication-templates/{template_id}")
def communication_template(template_id: str, db: DbSession, _: AdminUser) -> dict:
    item = template_or_default(db, template_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return public(item)


@router.patch("/communication-templates/{template_id}")
def update_template(template_id: str, payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    if template_or_default(db, template_id) is None:
        raise HTTPException(status_code=404, detail="Template not found")
    values = {key: str(value) for key, value in payload.items() if key in {"name", "subject", "body"}}
    values["updated_at"] = utc_now()
    db.communication_templates.update_one(
        {"_id": template_id}, {"$set": values, "$setOnInsert": {"created_at": utc_now()}}, upsert=True
    )
    audit(db, admin, "communication_template_updated", "communications", template_id, request)
    return public(db.communication_templates.find_one({"_id": template_id}))


@router.post("/communication-templates/{template_id}/preview")
def preview_template(template_id: str, payload: dict, db: DbSession, _: AdminUser) -> dict:
    item = template_or_default(db, template_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Template not found")
    variables = payload.get("variables", {}) if isinstance(payload.get("variables"), dict) else {}
    subject, body = item["subject"], item["body"]
    for key, value in variables.items():
        subject, body = subject.replace(f"{{{{{key}}}}}", str(value)), body.replace(f"{{{{{key}}}}}", str(value))
    return {"subject": subject, "body": body}


@router.post("/communication-templates/{template_id}/test", status_code=202)
def test_template(template_id: str, payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    if template_or_default(db, template_id) is None:
        raise HTTPException(status_code=404, detail="Template not found")
    job = document(type="template_test", template_id=template_id, recipient=payload.get("recipient"), status="queued")
    db.admin_jobs.insert_one(job)
    audit(db, admin, "communication_template_tested", "communications", template_id, request)
    return public(job)


@router.post("/communication-templates/{template_id}/reset")
def reset_template(template_id: str, request: Request, db: DbSession, admin: AdminUser) -> dict:
    item = next((value for value in default_templates() if value["_id"] == template_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Template not found")
    db.communication_templates.delete_one({"_id": template_id})
    audit(db, admin, "communication_template_reset", "communications", template_id, request)
    return public(item)


@router.get("/sessions")
def admin_sessions(
    db: DbSession, _: AdminUser, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
) -> list[dict]:
    cursor = db.admin_sessions.find({"revoked_at": None}).sort("last_seen_at", -1).skip(offset).limit(limit)
    return [public(item) for item in cursor]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: str, request: Request, db: DbSession, admin: AdminUser) -> None:
    session = db.admin_sessions.find_one({"_id": session_id, "revoked_at": None})
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    db.revoked_tokens.update_one(
        {"_id": session_id}, {"$setOnInsert": {"expires_at": session["expires_at"]}}, upsert=True
    )
    db.admin_sessions.update_one({"_id": session_id}, {"$set": {"revoked_at": utc_now()}})
    audit(db, admin, "admin_session_revoked", "security", session_id, request)


@router.post("/sessions/revoke-all")
def revoke_all_sessions(
    request: Request, db: DbSession, admin: AdminUser, credentials: BearerCredentials
) -> dict:
    now = utc_now()
    token = decode_token(credentials.credentials)
    db.users.update_many(
        {"is_admin": True},
        {"$set": {"sessions_invalid_before": now}, "$unset": {"session_exempt_jti": ""}},
    )
    db.users.update_one({"_id": admin["_id"]}, {"$set": {"session_exempt_jti": token["jti"]}})
    db.admin_sessions.update_many(
        {"_id": {"$ne": token["jti"]}, "revoked_at": None}, {"$set": {"revoked_at": now}}
    )
    audit(db, admin, "admin_sessions_revoked", "security", "all", request)
    return {"status": "revoked", "current_session_preserved": True}


@router.get("/permissions")
def permissions(_: AdminUser) -> list[dict]:
    return [{"key": key, "name": key.replace(".", " ").title()} for key in DEFAULT_PERMISSIONS]


@router.get("/roles")
def roles(db: DbSession, _: AdminUser) -> list[dict]:
    rows = list(db.admin_roles.find().sort("name", 1))
    if not rows:
        rows = [{"_id": "super-admin", "name": "Super admin", "permissions": DEFAULT_PERMISSIONS, "system": True}]
    return [public(item) for item in rows]


def validate_role(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    permissions = payload.get("permissions", [])
    if not name or not isinstance(permissions, list) or not set(permissions) <= set(DEFAULT_PERMISSIONS):
        raise HTTPException(status_code=422, detail="A name and valid permissions are required")
    return {"name": name, "permissions": permissions}


@router.post("/roles", status_code=201)
def create_role(payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    item = document(**validate_role(payload), system=False)
    db.admin_roles.insert_one(item)
    audit(db, admin, "admin_role_created", "security", item["_id"], request)
    return public(item)


@router.patch("/roles/{role_id}")
def update_role(role_id: str, payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    if role_id == "super-admin":
        raise HTTPException(status_code=409, detail="The system Super admin role cannot be modified")
    item = db.admin_roles.find_one_and_update(
        {"_id": role_id, "system": {"$ne": True}},
        {"$set": {**validate_role(payload), "updated_at": utc_now()}},
        return_document=True,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Role not found")
    audit(db, admin, "admin_role_updated", "security", role_id, request)
    return public(item)


@router.get("/security-events")
def security_events(
    db: DbSession, _: AdminUser, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
) -> list[dict]:
    query = {"target_type": "security"}
    return [public(item) for item in db.audit_logs.find(query).sort("created_at", -1).skip(offset).limit(limit)]


@router.get("/admins/{admin_id}/mfa-status")
def admin_mfa_status(admin_id: str, db: DbSession, _: AdminUser) -> dict:
    user = db.users.find_one({"_id": admin_id, "is_admin": True})
    if user is None:
        raise HTTPException(status_code=404, detail="Administrator not found")
    return {
        "admin_id": admin_id,
        "enrolled": bool(user.get("mfa_enrolled", False)),
        "enrolled_at": user.get("mfa_enrolled_at"),
        "methods": user.get("mfa_methods", []),
    }


@router.get("/settings/approvals")
def settings_approvals(
    db: DbSession, _: AdminUser, status: str | None = None, limit: int = Query(50, ge=1, le=100)
) -> list[dict]:
    query = {"status": status} if status else {}
    return [public(item) for item in db.settings_approvals.find(query).sort("created_at", -1).limit(limit)]


@router.post("/settings/approvals", status_code=201)
def request_settings_approval(payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    section = str(payload.get("section", ""))
    if section not in SETTINGS_SECTION_MODELS or not isinstance(payload.get("changes"), dict):
        raise HTTPException(status_code=422, detail="A valid section and changes are required")
    item = document(
        section=section,
        changes=payload["changes"],
        reason=str(payload.get("reason", "")),
        status="pending",
        requested_by=admin["_id"],
    )
    db.settings_approvals.insert_one(item)
    audit(db, admin, "settings_approval_requested", "settings", section, request)
    return public(item)


@router.post("/settings/approvals/{approval_id}/{decision}")
def decide_settings_approval(
    approval_id: str, decision: str, request: Request, db: DbSession, admin: AdminUser
) -> dict:
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=404, detail="Decision not found")
    item = db.settings_approvals.find_one_and_update(
        {"_id": approval_id, "status": "pending"},
        {"$set": {"status": f"{decision}d", "decided_by": admin["_id"], "decided_at": utc_now()}},
        return_document=True,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Pending approval not found")
    audit(db, admin, f"settings_approval_{decision}d", "settings", item["section"], request)
    return public(item)


@router.get("/integrations")
def integrations(db: DbSession, _: AdminUser) -> dict:
    return {key: mask_secrets(value) for key, value in integration_values(db).items()}


@router.get("/integrations/{provider}")
def integration(provider: str, db: DbSession, _: AdminUser) -> dict:
    if provider not in INTEGRATION_PROVIDERS:
        raise HTTPException(status_code=404, detail="Integration not found")
    return mask_secrets(integration_values(db)[provider])


@router.patch("/integrations/{provider}")
def configure_integration(provider: str, payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    if provider not in INTEGRATION_PROVIDERS:
        raise HTTPException(status_code=404, detail="Integration not found")
    allowed = {
        key: value
        for key, value in payload.items()
        if key in {"connected", "environment", "credentials", "credential_expires_at"}
    }
    credentials = allowed.pop("credentials", None)
    if credentials is not None:
        if not isinstance(credentials, dict):
            raise HTTPException(status_code=422, detail="credentials must be an object")
    current = integration_values(db)[provider]
    validated = IntegrationStatus.model_validate({**current, **allowed}).model_dump()
    allowed = {key: value for key, value in validated.items() if key != "credentials"}
    if credentials is not None:
        allowed["credentials"] = credentials
    allowed["updated_at"] = utc_now()
    db.platform_settings.update_one(
        {"_id": "platform"},
        {"$set": {f"settings.integrations.{provider}.{key}": value for key, value in allowed.items()}},
        upsert=True,
    )
    audit(db, admin, "integration_configured", "integrations", provider, request)
    return integration(provider, db, admin)


@router.post("/integrations/{provider}/test")
def test_integration(provider: str, request: Request, db: DbSession, admin: AdminUser) -> dict:
    current = integration(provider, db, admin)
    connected = bool(current.get("connected"))
    now = utc_now()
    timestamp_field = "last_success" if connected else "last_failure"
    db.platform_settings.update_one(
        {"_id": "platform"},
        {"$set": {f"settings.integrations.{provider}.{timestamp_field}": now}},
        upsert=True,
    )
    audit(db, admin, "integration_tested", "integrations", provider, request)
    return {"provider": provider, "status": "operational" if connected else "not_configured", "checked_at": now}


@router.post("/integrations/{provider}/connect")
def connect_integration(provider: str, request: Request, db: DbSession, admin: AdminUser) -> dict:
    return configure_integration(provider, {"connected": True}, request, db, admin)


@router.delete("/integrations/{provider}", status_code=204)
def disconnect_integration(provider: str, request: Request, db: DbSession, admin: AdminUser) -> None:
    if provider not in INTEGRATION_PROVIDERS:
        raise HTTPException(status_code=404, detail="Integration not found")
    db.platform_settings.update_one(
        {"_id": "platform"},
        {
            "$set": {f"settings.integrations.{provider}.connected": False},
            "$unset": {f"settings.integrations.{provider}.credentials": ""},
        },
        upsert=True,
    )
    audit(db, admin, "integration_disconnected", "integrations", provider, request)


def feature_flags(db: DbSession) -> dict:
    return section_settings_response(
        db, settings_item(db), "features", SETTINGS_SECTION_MODELS["features"]
    )["data"]


@router.get("/feature-flags")
def list_feature_flags(db: DbSession, _: AdminUser) -> dict:
    return feature_flags(db)


@router.patch("/feature-flags/{key}")
def update_feature_flag(key: str, payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    flags = feature_flags(db)
    if key not in flags:
        raise HTTPException(status_code=404, detail="Feature flag not found")
    before = flags[key]
    candidate = {**before, **payload}
    flag_model = SETTINGS_SECTION_MODELS["features"].model_fields[key].annotation
    after = flag_model.model_validate(candidate).model_dump()
    flags[key] = after
    persist_settings_section(db, admin, request, "features", flags)
    db.feature_flag_history.insert_one(document(key=key, before=before, after=after, admin_id=admin["_id"]))
    return {"key": key, **after}


@router.post("/feature-flags/{key}/impact-preview")
def feature_flag_impact(key: str, payload: dict, db: DbSession, _: AdminUser) -> dict:
    flags = feature_flags(db)
    if key not in flags:
        raise HTTPException(status_code=404, detail="Feature flag not found")
    rollout = int(payload.get("rollout", flags[key]["rollout"]))
    if not 0 <= rollout <= 100:
        raise HTTPException(status_code=422, detail="rollout must be between 0 and 100")
    users = db.users.count_documents({"is_active": True})
    return {"key": key, "rollout": rollout, "eligible_users": users, "estimated_users": round(users * rollout / 100)}


@router.post("/feature-flags/{key}/rollback")
def rollback_feature_flag(key: str, request: Request, db: DbSession, admin: AdminUser) -> dict:
    previous = db.feature_flag_history.find_one({"key": key}, sort=[("created_at", -1)])
    if previous is None:
        raise HTTPException(status_code=409, detail="No previous version is available")
    return update_feature_flag(key, previous["before"], request, db, admin)


@router.get("/feature-flags/{key}/history")
def feature_flag_history(key: str, db: DbSession, _: AdminUser) -> list[dict]:
    return [public(item) for item in db.feature_flag_history.find({"key": key}).sort("created_at", -1).limit(100)]


@router.get("/system/health/details")
def detailed_system_health(db: DbSession, _: AdminUser) -> dict:
    result = current_system_health(db)
    return {
        "overall_status": result["status"],
        "checked_at": result["checked_at"],
        "services": [
            {
                "key": key,
                "name": key.replace("_", " ").title(),
                "status": status,
                "response_time_ms": 0,
                "recent_errors": 0,
            }
            for key, status in result["services"].items()
        ],
        "queue_depth": db.admin_jobs.count_documents({"status": "queued"}),
        "application_version": settings.app_version,
        "environment": "production" if not settings.docs_enabled else "development",
    }


@router.get("/system/health")
def get_system_health(db: DbSession, _: AdminUser) -> dict:
    return detailed_system_health(db, _)


@router.post("/system/health/check")
def run_system_health_check(request: Request, db: DbSession, admin: AdminUser) -> dict:
    result = detailed_system_health(db, admin)
    audit(db, admin, "system_health_checked", "system", "health", request)
    return result


@router.get("/system/incidents")
def incidents(
    db: DbSession, _: AdminUser, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
) -> list[dict]:
    return [public(item) for item in db.system_incidents.find().sort("created_at", -1).skip(offset).limit(limit)]


def maintenance_settings(db: DbSession) -> dict:
    return section_settings_response(
        db, settings_item(db), "health", SETTINGS_SECTION_MODELS["health"]
    )["data"]


@router.get("/maintenance")
def get_maintenance(db: DbSession, _: AdminUser) -> dict:
    return maintenance_settings(db)


@router.post("/maintenance/preview")
def maintenance_preview(payload: dict, db: DbSession, _: AdminUser) -> dict:
    current = maintenance_settings(db)
    candidate = SETTINGS_SECTION_MODELS["health"].model_validate({**current, **payload}).model_dump()
    return {
        "effective_settings": candidate,
        "affected": {
            "active_users": db.users.count_documents({"is_active": True, "is_admin": {"$ne": True}}),
            "public_routes_restricted": candidate["maintenance_mode"],
        },
        "requires_confirmation": candidate["maintenance_mode"],
    }


def set_maintenance(
    enabled: bool, payload: dict, request: Request, db: DbSession, admin: dict
) -> dict:
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A change reason is required")
    current = maintenance_settings(db)
    allowed = {
        key: value
        for key, value in payload.items()
        if key in SETTINGS_SECTION_MODELS["health"].model_fields
    }
    candidate = SETTINGS_SECTION_MODELS["health"].model_validate(
        {**current, **allowed, "maintenance_mode": enabled}
    ).model_dump()
    response = persist_settings_section(db, admin, request, "health", candidate)
    latest_audit = db.audit_logs.find_one(
        {"action": "health_settings_updated", "admin_id": admin["_id"]}, sort=[("created_at", -1)]
    )
    if latest_audit:
        db.audit_logs.update_one({"_id": latest_audit["_id"]}, {"$set": {"metadata.reason": reason}})
    return response


@router.post("/maintenance/enable")
def enable_maintenance(payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    return set_maintenance(True, payload, request, db, admin)


@router.post("/maintenance/disable")
def disable_maintenance(payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    return set_maintenance(False, payload, request, db, admin)


@router.post("/data-exports", status_code=202)
def data_export(payload: dict, request: Request, db: DbSession, admin: AdminUser) -> dict:
    export_format = payload.get("format")
    if export_format is None:
        privacy = section_settings_response(db, settings_item(db), "privacy", PrivacySettings)["data"]
        export_format = privacy["export_format"]
    if export_format not in {"json", "csv"}:
        raise HTTPException(status_code=422, detail="format must be json or csv")
    job = document(type="platform_export", format=export_format, status="queued", requested_by=admin["_id"])
    db.admin_jobs.insert_one(job)
    audit(db, admin, "platform_export_requested", "privacy", job["_id"], request)
    return public(job)


@router.get("/data-exports/{export_id}")
def data_export_status(export_id: str, db: DbSession, _: AdminUser) -> dict:
    item = db.admin_jobs.find_one({"_id": export_id, "type": "platform_export"})
    if item is None:
        raise HTTPException(status_code=404, detail="Export job not found")
    return public(item)


@router.get("/deletion-requests")
def list_deletion_requests(
    db: DbSession,
    _: AdminUser,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    query = {"status": status} if status else {}
    return [
        public(item)
        for item in db.account_deletion_requests.find(query).sort("created_at", -1).skip(offset).limit(limit)
    ]


@router.get("/deletion-requests/{request_id}")
def deletion_request(request_id: str, db: DbSession, _: AdminUser) -> dict:
    item = db.account_deletion_requests.find_one({"_id": request_id})
    if item is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    return public(item)


def decide_deletion_request(
    request_id: str, decision: str, payload: dict, request: Request, db: DbSession, admin: dict
) -> dict:
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A decision reason is required")
    item = db.account_deletion_requests.find_one_and_update(
        {"_id": request_id, "status": "pending"},
        {"$set": {"status": decision, "reason": reason, "decided_by": admin["_id"], "decided_at": utc_now()}},
        return_document=True,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Pending deletion request not found")
    audit(db, admin, f"deletion_request_{decision}", "privacy", request_id, request)
    return public(item)


@router.post("/deletion-requests/{request_id}/approve")
def approve_deletion_request(
    request_id: str, payload: dict, request: Request, db: DbSession, admin: AdminUser
) -> dict:
    return decide_deletion_request(request_id, "approved", payload, request, db, admin)


@router.post("/deletion-requests/{request_id}/reject")
def reject_deletion_request(
    request_id: str, payload: dict, request: Request, db: DbSession, admin: AdminUser
) -> dict:
    return decide_deletion_request(request_id, "rejected", payload, request, db, admin)


@router.get("/backups/status")
def backup_status(db: DbSession, _: AdminUser) -> dict:
    latest = db.backups.find_one(sort=[("created_at", -1)])
    return {
        "status": latest.get("status", "not_configured") if latest else "not_configured",
        "last_backup_at": latest.get("created_at") if latest else None,
        "next_backup_at": latest.get("next_backup_at") if latest else None,
    }


@router.post("/privacy/impact-preview")
def privacy_impact_preview(payload: dict, db: DbSession, _: AdminUser) -> dict:
    current = section_settings_response(db, settings_item(db), "privacy", PrivacySettings)["data"]
    candidate = PrivacySettings.model_validate({**current, **payload}).model_dump()
    now = utc_now()
    return {
        "effective_settings": candidate,
        "affected": {
            "users_eligible_for_cleanup": db.users.count_documents(
                {"created_at": {"$lt": now - timedelta(days=candidate["user_retention_days"])}}
            ),
            "analytics_events": db.analytics_events.count_documents({}),
        },
    }


@router.post("/privacy/anonymization-jobs", status_code=202)
def create_anonymization_job(request: Request, db: DbSession, admin: AdminUser) -> dict:
    job = document(type="privacy_anonymization", status="queued", requested_by=admin["_id"])
    db.admin_jobs.insert_one(job)
    audit(db, admin, "anonymization_requested", "privacy", job["_id"], request)
    return public(job)


@router.get("/settings/audit-log")
def settings_audit_log(
    db: DbSession,
    _: AdminUser,
    section: str | None = None,
    admin_id: str | None = None,
    action: str | None = None,
    success: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    query: dict = {"target_type": {"$in": ["settings", "security", "integrations", "privacy", "system"]}}
    if section:
        query["target_id"] = section
    if admin_id:
        query["admin_id"] = admin_id
    if action:
        query["action"] = {"$regex": action, "$options": "i"}
    if success is not None:
        query["success"] = success
    if date_from or date_to:
        query["created_at"] = {}
        if date_from:
            query["created_at"]["$gte"] = date_from
        if date_to:
            query["created_at"]["$lte"] = date_to
    result = []
    for item in db.audit_logs.find(query).sort("created_at", -1).skip(offset).limit(limit):
        administrator = db.users.find_one({"_id": item.get("admin_id")}, {"full_name": 1}) or {}
        metadata = mask_secrets(item.get("metadata", {}))
        result.append(
            {
                **public(item),
                "admin_name": administrator.get("full_name", "Administrator"),
                "section": item.get("target_id"),
                "success": item.get("success", True),
                "metadata": metadata,
                "request_id": item.get("request_id"),
            }
        )
    return result
