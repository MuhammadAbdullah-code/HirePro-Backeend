# ruff: noqa: B008

import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from app.api.deps import BusinessUser, CustomerUser, DbSession
from app.core.security import hash_password, verify_password
from app.models import document, public, utc_now
from app.schemas.api import ProfileUpdate

router = APIRouter()


def owned(db: DbSession, collection: str, item_id: str, owner: str, owner_field: str = "user_id") -> dict:
    item = db[collection].find_one({"_id": item_id, owner_field: owner, "deleted_at": None})
    if item is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return item


def page(cursor: Any, offset: int, limit: int) -> list[dict]:
    return [public(item) for item in cursor.skip(offset).limit(limit)]


def preferences(db: DbSession, user_id: str) -> dict:
    defaults = {
        "email_notifications": True,
        "push_notifications": True,
        "quote_notifications": True,
        "marketing_notifications": False,
        "language": "en",
        "theme": "system",
    }
    db.user_preferences.update_one({"_id": user_id}, {"$setOnInsert": defaults}, upsert=True)
    return db.user_preferences.find_one({"_id": user_id})


@router.get("/customer/dashboard", tags=["customer"])
def customer_dashboard(db: DbSession, user: CustomerUser) -> dict:
    request_ids = [x["_id"] for x in db.customer_requests.find({"user_id": user["_id"], "deleted_at": None})]
    return {
        "stats": {
            "active_requests": db.customer_requests.count_documents(
                {"user_id": user["_id"], "status": {"$in": ["open", "receiving_quotes"]}, "deleted_at": None}
            ),
            "pros_contacted": len(db.provider_quotes.distinct("provider_id", {"request_id": {"$in": request_ids}})),
            "saved_profiles": db.favorites.count_documents({"user_id": user["_id"]}),
            "total_budget": sum(
                x.get("budget_max", 0) or 0 for x in db.customer_requests.find({"user_id": user["_id"]})
            ),
            "unread_notifications": db.notifications.count_documents({"user_id": user["_id"], "is_read": False}),
        },
        "recent_activity": page(db.request_timeline.find({"user_id": user["_id"]}).sort("created_at", -1), 0, 10),
        "priority_request": public(
            db.customer_requests.find_one({"user_id": user["_id"], "status": "receiving_quotes"})
        ),
        "recommended_professionals": page(db.businesses.find({"is_active": True, "is_verified": True}), 0, 6),
    }


@router.post("/customer/requests", status_code=201, tags=["customer-requests"])
def create_request(payload: dict = Body(...), *, db: DbSession, user: CustomerUser) -> dict:
    for field in ("category_id", "title", "description", "city"):
        if not payload.get(field):
            raise HTTPException(status_code=422, detail=f"{field} is required")
    if not db.categories.find_one({"_id": payload["category_id"]}):
        raise HTTPException(status_code=400, detail="Invalid category")
    item = document(
        user_id=user["_id"],
        status="receiving_quotes",
        quotes_count=0,
        expires_at=utc_now() + timedelta(days=7),
        deleted_at=None,
        **payload,
    )
    db.customer_requests.insert_one(item)
    db.request_timeline.insert_one(document(request_id=item["_id"], user_id=user["_id"], event="created"))
    return {**public(item), "timeline": []}


@router.get("/customer/requests", tags=["customer-requests"])
def customer_requests(
    db: DbSession, user: CustomerUser, status: str | None = None, limit: int = Query(20, le=100), offset: int = 0
) -> list[dict]:
    query: dict = {"user_id": user["_id"], "deleted_at": None}
    if status:
        query["status"] = status
    return page(db.customer_requests.find(query).sort("created_at", -1), offset, limit)


@router.get("/customer/requests/{request_id}", tags=["customer-requests"])
def customer_request(request_id: str, db: DbSession, user: CustomerUser) -> dict:
    item = owned(db, "customer_requests", request_id, user["_id"])
    return {
        **public(item),
        "timeline": page(db.request_timeline.find({"request_id": request_id}).sort("created_at", 1), 0, 100),
    }


@router.patch("/customer/requests/{request_id}", tags=["customer-requests"])
def update_request(request_id: str, payload: dict = Body(...), *, db: DbSession, user: CustomerUser) -> dict:
    item = owned(db, "customer_requests", request_id, user["_id"])
    if item["status"] not in ("open", "receiving_quotes"):
        raise HTTPException(status_code=409, detail="Request can no longer be edited")
    allowed = {
        k: v
        for k, v in payload.items()
        if k in {"title", "description", "city", "address", "budget_min", "budget_max", "required_date", "attachments"}
    }
    allowed["updated_at"] = utc_now()
    db.customer_requests.update_one({"_id": request_id}, {"$set": allowed})
    return public(db.customer_requests.find_one({"_id": request_id}))


@router.delete("/customer/requests/{request_id}", status_code=204, tags=["customer-requests"])
def delete_request(request_id: str, db: DbSession, user: CustomerUser) -> None:
    owned(db, "customer_requests", request_id, user["_id"])
    db.customer_requests.update_one({"_id": request_id}, {"$set": {"deleted_at": utc_now()}})


@router.post("/customer/requests/{request_id}/{action}", tags=["customer-requests"])
def request_action(request_id: str, action: str, db: DbSession, user: CustomerUser) -> dict:
    if action not in {"cancel", "close", "extend"}:
        raise HTTPException(status_code=404, detail="Action not found")
    item = owned(db, "customer_requests", request_id, user["_id"])
    values = {"updated_at": utc_now()}
    values["expires_at" if action == "extend" else "status"] = (
        item.get("expires_at", utc_now()) + timedelta(days=7) if action == "extend" else f"{action}d"
    )
    db.customer_requests.update_one({"_id": request_id}, {"$set": values})
    db.request_timeline.insert_one(document(request_id=request_id, user_id=user["_id"], event=action))
    return public(db.customer_requests.find_one({"_id": request_id}))


def quote_for_customer(db: DbSession, quote_id: str, user_id: str) -> dict:
    quote = db.provider_quotes.find_one({"_id": quote_id, "deleted_at": None})
    if quote is None or not db.customer_requests.find_one({"_id": quote.get("request_id"), "user_id": user_id}):
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


@router.get("/customer/requests/{request_id}/quotes", tags=["customer-quotes"])
def request_quotes(request_id: str, db: DbSession, user: CustomerUser) -> list[dict]:
    owned(db, "customer_requests", request_id, user["_id"])
    return page(db.provider_quotes.find({"request_id": request_id, "deleted_at": None}), 0, 100)


@router.get("/customer/quotes/{quote_id}", tags=["customer-quotes"])
def customer_quote(quote_id: str, db: DbSession, user: CustomerUser) -> dict:
    return public(quote_for_customer(db, quote_id, user["_id"]))


@router.post("/customer/quotes/{quote_id}/{action}", tags=["customer-quotes"])
def customer_quote_action(quote_id: str, action: str, db: DbSession, user: CustomerUser) -> dict:
    if action not in {"accept", "decline"}:
        raise HTTPException(status_code=404, detail="Action not found")
    quote = quote_for_customer(db, quote_id, user["_id"])
    db.provider_quotes.update_one({"_id": quote_id}, {"$set": {"status": f"{action}ed", "updated_at": utc_now()}})
    if action == "accept":
        db.provider_quotes.update_many(
            {"request_id": quote["request_id"], "_id": {"$ne": quote_id}}, {"$set": {"status": "declined"}}
        )
        db.customer_requests.update_one({"_id": quote["request_id"]}, {"$set": {"status": "quote_accepted"}})
    return public(db.provider_quotes.find_one({"_id": quote_id}))


def quote_messages(db: DbSession, quote_id: str) -> list[dict]:
    return page(db.quote_messages.find({"quote_id": quote_id}).sort("created_at", 1), 0, 200)


@router.get("/customer/quotes/{quote_id}/messages", tags=["messages"])
def customer_messages(quote_id: str, db: DbSession, user: CustomerUser) -> list[dict]:
    quote_for_customer(db, quote_id, user["_id"])
    return quote_messages(db, quote_id)


@router.post("/customer/quotes/{quote_id}/messages", status_code=201, tags=["messages"])
def customer_send_message(quote_id: str, payload: dict = Body(...), *, db: DbSession, user: CustomerUser) -> dict:
    quote_for_customer(db, quote_id, user["_id"])
    item = document(
        quote_id=quote_id, sender_id=user["_id"], body=str(payload.get("body", "")).strip(), read_by=[user["_id"]]
    )
    if not item["body"]:
        raise HTTPException(status_code=422, detail="body is required")
    db.quote_messages.insert_one(item)
    return public(item)


@router.post("/customer/quotes/{quote_id}/messages/read", tags=["messages"])
def customer_read_messages(quote_id: str, db: DbSession, user: CustomerUser) -> dict:
    quote_for_customer(db, quote_id, user["_id"])
    result = db.quote_messages.update_many({"quote_id": quote_id}, {"$addToSet": {"read_by": user["_id"]}})
    return {"updated": result.modified_count}


@router.get("/customer/favorites", tags=["customer-favorites"])
def customer_favorites(db: DbSession, user: CustomerUser) -> list[dict]:
    ids = db.favorites.distinct("business_id", {"user_id": user["_id"]})
    return page(db.businesses.find({"_id": {"$in": ids}, "is_active": True}), 0, 100)


@router.post("/customer/favorites/compare", tags=["customer-favorites"])
def compare_favorites(payload: dict = Body(...), *, db: DbSession, user: CustomerUser) -> list[dict]:
    ids = payload.get("business_ids", [])[:5]
    saved = set(db.favorites.distinct("business_id", {"user_id": user["_id"], "business_id": {"$in": ids}}))
    return [public(x) for x in db.businesses.find({"_id": {"$in": list(saved)}})]


@router.post("/customer/favorites/{business_id}", status_code=201, tags=["customer-favorites"])
def save_favorite(business_id: str, db: DbSession, user: CustomerUser) -> dict:
    if not db.businesses.find_one({"_id": business_id, "is_active": True}):
        raise HTTPException(status_code=404, detail="Business not found")
    db.favorites.update_one(
        {"user_id": user["_id"], "business_id": business_id},
        {"$setOnInsert": document(user_id=user["_id"], business_id=business_id)},
        upsert=True,
    )
    return {"is_favorite": True}


@router.delete("/customer/favorites/{business_id}", status_code=204, tags=["customer-favorites"])
def remove_favorite(business_id: str, db: DbSession, user: CustomerUser) -> None:
    db.favorites.delete_one({"user_id": user["_id"], "business_id": business_id})


def notification_routes(prefix: str, role_dependency: Any) -> None:
    @router.get(f"/{prefix}/notifications", tags=[f"{prefix}-notifications"])
    def listing(
        db: DbSession, user: role_dependency, unread: bool | None = None, type: str | None = None
    ) -> list[dict]:
        query: dict = {"user_id": user["_id"]}
        if unread is not None:
            query["is_read"] = not unread
        if type:
            query["type"] = type
        return page(db.notifications.find(query).sort("created_at", -1), 0, 100)

    @router.get(f"/{prefix}/notifications/unread-count", tags=[f"{prefix}-notifications"])
    def unread_count(db: DbSession, user: role_dependency) -> dict:
        return {"count": db.notifications.count_documents({"user_id": user["_id"], "is_read": False})}

    @router.patch(f"/{prefix}/notifications/read-all", tags=[f"{prefix}-notifications"])
    def read_all(db: DbSession, user: role_dependency) -> dict:
        result = db.notifications.update_many({"user_id": user["_id"], "is_read": False}, {"$set": {"is_read": True}})
        return {"updated": result.modified_count}

    @router.patch(f"/{prefix}/notifications/{{notification_id}}/read", tags=[f"{prefix}-notifications"])
    def read_one(notification_id: str, db: DbSession, user: role_dependency) -> dict:
        item = db.notifications.find_one_and_update(
            {"_id": notification_id, "user_id": user["_id"]}, {"$set": {"is_read": True}}, return_document=True
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        return public(item)

    @router.delete(f"/{prefix}/notifications/{{notification_id}}", status_code=204, tags=[f"{prefix}-notifications"])
    def remove(notification_id: str, db: DbSession, user: role_dependency) -> None:
        db.notifications.delete_one({"_id": notification_id, "user_id": user["_id"]})


notification_routes("customer", CustomerUser)
notification_routes("provider", BusinessUser)


def account_routes(prefix: str, role_dependency: Any) -> None:
    @router.get(f"/{prefix}/profile", tags=[f"{prefix}-settings"])
    def profile(user: role_dependency) -> dict:
        return public(user)

    @router.patch(f"/{prefix}/profile", tags=[f"{prefix}-settings"])
    def update_profile(payload: ProfileUpdate, *, db: DbSession, user: role_dependency) -> dict:
        values: dict[str, Any] = {}
        if payload.full_name is not None:
            values["full_name"] = payload.full_name.strip()
        if payload.phone is not None:
            phone = payload.phone.strip()
            if phone and not re.fullmatch(r"\+?[0-9][0-9 ()-]{6,28}[0-9]", phone):
                raise HTTPException(status_code=422, detail="Invalid phone number format")
            values["phone"] = phone or None
        if payload.profile_image_url is not None:
            image_url = payload.profile_image_url.strip()
            if image_url and not image_url.startswith("https://res.cloudinary.com/"):
                raise HTTPException(status_code=422, detail="profile_image_url must be a secure Cloudinary URL")
            values["profile_image_url"] = image_url or None

        normalized_email = payload.email.strip().lower() if payload.email is not None else None
        email_changed = normalized_email is not None and normalized_email != user["email"]
        if email_changed and not payload.current_password:
            raise HTTPException(status_code=422, detail="current_password is required to change email")
        if email_changed or payload.new_password is not None:
            if not verify_password(payload.current_password or "", user["password_hash"]):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
        if payload.email is not None:
            email = normalized_email or ""
            if email_changed and db.users.find_one({"email": email, "_id": {"$ne": user["_id"]}}):
                raise HTTPException(status_code=409, detail="Email is already registered")
            values["email"] = email
        if payload.new_password is not None:
            values["password_hash"] = hash_password(payload.new_password)

        try:
            db.users.update_one({"_id": user["_id"]}, {"$set": {**values, "updated_at": utc_now()}})
        except DuplicateKeyError as exc:
            raise HTTPException(status_code=409, detail="Email is already registered") from exc
        return public(db.users.find_one({"_id": user["_id"]}))

    @router.patch(f"/{prefix}/password", status_code=204, tags=[f"{prefix}-settings"])
    def change_password(payload: dict = Body(...), *, db: DbSession, user: role_dependency) -> None:
        if not verify_password(str(payload.get("current_password", "")), user["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        password = str(payload.get("new_password", ""))
        if len(password) < 8:
            raise HTTPException(status_code=422, detail="New password must contain at least 8 characters")
        db.users.update_one(
            {"_id": user["_id"]}, {"$set": {"password_hash": hash_password(password), "updated_at": utc_now()}}
        )

    @router.get(f"/{prefix}/preferences", tags=[f"{prefix}-settings"])
    def get_preferences(db: DbSession, user: role_dependency) -> dict:
        return preferences(db, user["_id"])

    @router.patch(f"/{prefix}/preferences", tags=[f"{prefix}-settings"])
    def patch_preferences(payload: dict = Body(...), *, db: DbSession, user: role_dependency) -> dict:
        preferences(db, user["_id"])
        db.user_preferences.update_one({"_id": user["_id"]}, {"$set": payload})
        return db.user_preferences.find_one({"_id": user["_id"]})

    @router.delete(f"/{prefix}/account", status_code=204, tags=[f"{prefix}-settings"])
    def delete_account(db: DbSession, user: role_dependency) -> None:
        db.users.update_one({"_id": user["_id"]}, {"$set": {"is_active": False, "deleted_at": utc_now()}})


account_routes("customer", CustomerUser)
account_routes("provider", BusinessUser)
