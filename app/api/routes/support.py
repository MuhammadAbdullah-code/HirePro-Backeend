# ruff: noqa: B008

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from app.api.deps import CurrentUser, DbSession
from app.core.cloudinary import delete_asset, signed_upload_parameters, upload_bytes
from app.core.config import settings
from app.models import document, public, utc_now

router = APIRouter(tags=["support"])
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}


@router.post("/uploads", status_code=201)
async def upload_file(db: DbSession, user: CurrentUser, file: UploadFile = File(...)) -> dict:
    suffix = ALLOWED_TYPES.get(file.content_type or "")
    if suffix is None:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, WebP and PDF files are allowed")
    content = await file.read(settings.maximum_upload_bytes + 1)
    if len(content) > settings.maximum_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the configured size limit")
    if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in content:
        raise HTTPException(status_code=422, detail="File failed malware screening")
    generated_name = f"{uuid4().hex}{suffix}"
    storage_provider = "local"
    asset_url = ""
    public_id = ""
    resource_type = "image" if (file.content_type or "").startswith("image/") else "raw"
    if settings.cloudinary_enabled:
        try:
            result = upload_bytes(content, public_id=generated_name.rsplit(".", 1)[0], resource_type=resource_type)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Cloudinary upload failed") from exc
        storage_provider = "cloudinary"
        asset_url = result["secure_url"]
        public_id = result["public_id"]
    else:
        directory = Path(settings.upload_directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / generated_name).write_bytes(content)
    item = document(
        user_id=user["_id"],
        original_name=file.filename,
        stored_name=generated_name,
        content_type=file.content_type,
        size=len(content),
        sha256=sha256(content).hexdigest(),
        storage_provider=storage_provider,
        public_id=public_id,
        resource_type=resource_type,
    )
    db.uploads.insert_one(item)
    return {**public(item), "url": asset_url or f"/api/v1/uploads/{item['_id']}"}


@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: str, db: DbSession, user: CurrentUser) -> None:
    item = db.uploads.find_one({"_id": upload_id, "user_id": user["_id"]})
    if item is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    if item.get("storage_provider") == "cloudinary":
        try:
            delete_asset(item["public_id"], resource_type=item.get("resource_type", "image"))
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Cloudinary deletion failed") from exc
    else:
        path = Path(settings.upload_directory).resolve() / item["stored_name"]
        if path.is_file():
            path.unlink()
    db.uploads.delete_one({"_id": upload_id})


@router.post("/uploads/presigned-url")
def presigned_upload(_: CurrentUser) -> dict:
    if not settings.cloudinary_enabled:
        raise HTTPException(status_code=503, detail="Cloudinary is not configured; use POST /uploads")
    return signed_upload_parameters()


@router.post("/webhooks/payments")
def payment_webhook(
    payload: dict, db: DbSession, x_webhook_secret: str = Header(""), x_event_id: str = Header("")
) -> dict:
    if not x_webhook_secret or x_webhook_secret != settings.payment_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    if not x_event_id:
        raise HTTPException(status_code=400, detail="X-Event-Id is required")
    if db.webhook_events.find_one({"_id": x_event_id}):
        return {"status": "already_processed"}
    session_id = payload.get("checkout_session_id")
    event_type = payload.get("type")
    subscription = db.subscriptions.find_one({"provider_session_id": session_id})
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription session not found")
    status = {"payment.succeeded": "active", "subscription.cancelled": "cancelled"}.get(event_type)
    if status is None:
        raise HTTPException(status_code=400, detail="Unsupported payment event")
    db.subscriptions.update_one({"_id": subscription["_id"]}, {"$set": {"status": status, "updated_at": utc_now()}})
    db.webhook_events.insert_one(document(id=x_event_id, event_type=event_type))
    return {"status": "processed"}
