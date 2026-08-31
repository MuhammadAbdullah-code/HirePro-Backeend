# ruff: noqa: B008

from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Query

from app.api.deps import BusinessUser, DbSession
from app.models import document, new_id, public, utc_now

router = APIRouter(prefix="/provider", tags=["provider"])


def provider_business(db: DbSession, user_id: str, required: bool = True) -> dict | None:
    item = db.businesses.find_one({"owner_id": user_id, "deleted_at": None})
    if required and item is None:
        raise HTTPException(status_code=404, detail="Business profile not found")
    return item


def provider_quote(db: DbSession, quote_id: str, user_id: str) -> dict:
    item = db.provider_quotes.find_one({"_id": quote_id, "provider_id": user_id, "deleted_at": None})
    if item is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return item


def visible_request(db: DbSession, request_id: str, user_id: str) -> dict:
    item = db.customer_requests.find_one({"_id": request_id, "deleted_at": None})
    business = provider_business(db, user_id)
    if item is None or item.get("category_id") != business.get("category_id"):
        raise HTTPException(status_code=404, detail="Request not found")
    return item


@router.get("/dashboard")
def dashboard(db: DbSession, user: BusinessUser) -> dict:
    business = provider_business(db, user["_id"], required=False)
    category_id = business.get("category_id") if business else None
    profile_steps = [
        {
            "key": "basic_info",
            "label": "Basic information",
            "completed": bool(business),
            "action_url": "/provider/profile",
        },
        {
            "key": "photos",
            "label": "Business photos",
            "completed": bool(business and db.business_photos.find_one({"business_id": business["_id"]})),
            "action_url": "/provider/profile/photos",
        },
        {
            "key": "verification",
            "label": "Verification",
            "completed": bool(business and business.get("is_verified")),
            "action_url": "/provider/verification",
        },
    ]
    completed = sum(step["completed"] for step in profile_steps)
    request_filter = {"category_id": category_id, "status": {"$in": ["open", "receiving_quotes"]}, "deleted_at": None}
    quote_filter = {"provider_id": user["_id"], "deleted_at": None}
    submitted = db.provider_quotes.count_documents(quote_filter)
    accepted = db.provider_quotes.count_documents({**quote_filter, "status": "accepted"})
    return {
        "profile_completion": {"percentage": round(completed / len(profile_steps) * 100), "steps": profile_steps},
        "stats": {
            "new_quote_requests": db.customer_requests.count_documents(request_filter),
            "profile_views": business.get("view_count", 0) if business else 0,
            "average_response_minutes": 0,
            "win_rate": round(accepted / submitted * 100, 1) if submitted else 0,
            "view_to_quote_conversion": 0,
        },
        "latest_requests": [
            public(x) for x in db.customer_requests.find(request_filter).sort("created_at", -1).limit(5)
        ],
        "notifications": [
            public(x) for x in db.notifications.find({"user_id": user["_id"]}).sort("created_at", -1).limit(5)
        ],
    }


@router.get("/requests")
def requests(
    db: DbSession,
    user: BusinessUser,
    status: str | None = None,
    urgency: str | None = None,
    limit: int = Query(20, le=100),
    offset: int = 0,
) -> list[dict]:
    business = provider_business(db, user["_id"])
    query: dict = {"category_id": business["category_id"], "deleted_at": None}
    query["status"] = status if status else {"$in": ["open", "receiving_quotes"]}
    if urgency:
        query["urgency"] = urgency
    result = []
    for item in db.customer_requests.find(query).sort("created_at", -1).skip(offset).limit(limit):
        customer = db.users.find_one({"_id": item["user_id"]}, {"full_name": 1}) or {}
        result.append(
            {**public(item), "customer": {"id": item["user_id"], "full_name": customer.get("full_name", "Customer")}}
        )
    return result


@router.get("/requests/{request_id}")
def request_detail(request_id: str, db: DbSession, user: BusinessUser) -> dict:
    return public(visible_request(db, request_id, user["_id"]))


@router.post("/requests/{request_id}/respond", status_code=201)
def respond_to_request(request_id: str, payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
    visible_request(db, request_id, user["_id"])
    return create_quote({**payload, "request_id": request_id}, db=db, user=user)


@router.post("/requests/{request_id}/decline", status_code=204)
def decline_request(request_id: str, db: DbSession, user: BusinessUser) -> None:
    visible_request(db, request_id, user["_id"])
    db.provider_request_actions.update_one(
        {"provider_id": user["_id"], "request_id": request_id},
        {"$set": {"action": "declined", "updated_at": utc_now()}},
        upsert=True,
    )


@router.post("/quotes", status_code=201)
def create_quote(payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
    request_id = str(payload.get("request_id", ""))
    request = visible_request(db, request_id, user["_id"])
    if db.provider_quotes.find_one({"request_id": request_id, "provider_id": user["_id"], "deleted_at": None}):
        raise HTTPException(status_code=409, detail="You already responded to this request")
    if not isinstance(payload.get("amount"), (int, float)) or payload["amount"] < 0:
        raise HTTPException(status_code=422, detail="A valid amount is required")
    item = document(provider_id=user["_id"], status="pending", deleted_at=None, **payload)
    db.provider_quotes.insert_one(item)
    db.customer_requests.update_one({"_id": request_id}, {"$inc": {"quotes_count": 1}})
    db.notifications.insert_one(
        document(
            user_id=request["user_id"],
            type="quote_received",
            title="New quote",
            message="A provider sent a quote",
            is_read=False,
        )
    )
    return public(item)


@router.get("/quotes")
def quotes(
    db: DbSession, user: BusinessUser, status: str | None = None, limit: int = Query(20, le=100), offset: int = 0
) -> list[dict]:
    query: dict = {"provider_id": user["_id"], "deleted_at": None}
    if status:
        query["status"] = status
    return [public(x) for x in db.provider_quotes.find(query).sort("created_at", -1).skip(offset).limit(limit)]


@router.get("/quotes/{quote_id}")
def quote_detail(quote_id: str, db: DbSession, user: BusinessUser) -> dict:
    return public(provider_quote(db, quote_id, user["_id"]))


@router.patch("/quotes/{quote_id}")
def update_quote(quote_id: str, payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
    item = provider_quote(db, quote_id, user["_id"])
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="Only pending quotes can be updated")
    allowed = {k: v for k, v in payload.items() if k in {"amount", "message", "estimated_duration", "valid_until"}}
    db.provider_quotes.update_one({"_id": quote_id}, {"$set": {**allowed, "updated_at": utc_now()}})
    return public(db.provider_quotes.find_one({"_id": quote_id}))


@router.post("/quotes/{quote_id}/withdraw")
def withdraw_quote(quote_id: str, db: DbSession, user: BusinessUser) -> dict:
    provider_quote(db, quote_id, user["_id"])
    db.provider_quotes.update_one({"_id": quote_id}, {"$set": {"status": "withdrawn", "updated_at": utc_now()}})
    return public(db.provider_quotes.find_one({"_id": quote_id}))


@router.get("/quotes/{quote_id}/messages")
def messages(quote_id: str, db: DbSession, user: BusinessUser) -> list[dict]:
    provider_quote(db, quote_id, user["_id"])
    return [public(x) for x in db.quote_messages.find({"quote_id": quote_id}).sort("created_at", 1)]


@router.post("/quotes/{quote_id}/messages", status_code=201)
def send_message(quote_id: str, payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
    provider_quote(db, quote_id, user["_id"])
    body = str(payload.get("body", "")).strip()
    if not body:
        raise HTTPException(status_code=422, detail="body is required")
    item = document(quote_id=quote_id, sender_id=user["_id"], body=body, read_by=[user["_id"]])
    db.quote_messages.insert_one(item)
    return public(item)


@router.post("/quotes/{quote_id}/messages/read")
def read_messages(quote_id: str, db: DbSession, user: BusinessUser) -> dict:
    provider_quote(db, quote_id, user["_id"])
    result = db.quote_messages.update_many({"quote_id": quote_id}, {"$addToSet": {"read_by": user["_id"]}})
    return {"updated": result.modified_count}


@router.get("/business")
def get_business(db: DbSession, user: BusinessUser) -> dict:
    return public(provider_business(db, user["_id"]))


@router.post("/business", status_code=201)
def create_business(payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
    if provider_business(db, user["_id"], required=False):
        raise HTTPException(status_code=409, detail="Business profile already exists")
    from app.api.routes.catalog import slugify

    if not db.categories.find_one({"_id": payload.get("category_id")}):
        raise HTTPException(status_code=400, detail="Invalid category")
    item = document(
        owner_id=user["_id"],
        slug=f"{slugify(str(payload.get('name', 'business')))}-{new_id()[:8]}",
        is_verified=False,
        is_active=True,
        view_count=0,
        deleted_at=None,
        **payload,
    )
    db.businesses.insert_one(item)
    return public(item)


@router.patch("/business")
def update_business(payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
    item = provider_business(db, user["_id"])
    blocked = {"_id", "owner_id", "is_verified", "created_at", "deleted_at"}
    db.businesses.update_one(
        {"_id": item["_id"]},
        {"$set": {**{k: v for k, v in payload.items() if k not in blocked}, "updated_at": utc_now()}},
    )
    return public(db.businesses.find_one({"_id": item["_id"]}))


def register_resource(name: str, collection: str) -> None:
    base = f"/business/{name}"

    @router.get(base, name=f"list_provider_{name}")
    def listing(db: DbSession, user: BusinessUser) -> list[dict]:
        business = provider_business(db, user["_id"])
        return [public(x) for x in db[collection].find({"business_id": business["_id"]}).sort("sort_order", 1)]

    @router.post(base, status_code=201, name=f"create_provider_{name}")
    def create(payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
        business = provider_business(db, user["_id"])
        item = document(business_id=business["_id"], **payload)
        db[collection].insert_one(item)
        return public(item)

    @router.patch(f"{base}/{{item_id}}", name=f"update_provider_{name}")
    def update(item_id: str, payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
        business = provider_business(db, user["_id"])
        item = db[collection].find_one_and_update(
            {"_id": item_id, "business_id": business["_id"]},
            {"$set": {**payload, "updated_at": utc_now()}},
            return_document=True,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        return public(item)

    @router.delete(f"{base}/{{item_id}}", status_code=204, name=f"delete_provider_{name}")
    def remove(item_id: str, db: DbSession, user: BusinessUser) -> None:
        business = provider_business(db, user["_id"])
        result = db[collection].delete_one({"_id": item_id, "business_id": business["_id"]})
        if not result.deleted_count:
            raise HTTPException(status_code=404, detail="Resource not found")


for resource_name, collection_name in (
    ("services", "business_services"),
    ("service-areas", "business_service_areas"),
    ("photos", "business_photos"),
    ("credentials", "business_credentials"),
):
    register_resource(resource_name, collection_name)


@router.post("/business/photos/reorder")
def reorder_photos(payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
    business = provider_business(db, user["_id"])
    for position, photo_id in enumerate(payload.get("photo_ids", [])):
        db.business_photos.update_one(
            {"_id": photo_id, "business_id": business["_id"]}, {"$set": {"sort_order": position}}
        )
    return {"updated": len(payload.get("photo_ids", []))}


@router.get("/verification")
def verification(db: DbSession, user: BusinessUser) -> dict:
    business = provider_business(db, user["_id"])
    return public(db.verification_requests.find_one({"business_id": business["_id"]})) or {
        "status": "not_submitted",
        "required_documents": [],
    }


@router.post("/verification", status_code=201)
def submit_verification(payload: dict = Body(default={}), *, db: DbSession, user: BusinessUser) -> dict:
    business = provider_business(db, user["_id"])
    existing = db.verification_requests.find_one({"business_id": business["_id"], "status": "pending"})
    if existing:
        raise HTTPException(status_code=409, detail="Verification is already pending")
    item = document(
        business_id=business["_id"],
        provider_id=user["_id"],
        status="pending",
        submitted_at=utc_now(),
        reviewed_at=None,
        rejection_reason=None,
        required_documents=payload.get("documents", []),
    )
    db.verification_requests.insert_one(item)
    return public(item)


def singleton_settings(name: str, collection: str, defaults: dict) -> None:
    @router.get(f"/business/{name}", name=f"get_provider_{name}")
    def get(db: DbSession, user: BusinessUser) -> dict:
        business = provider_business(db, user["_id"])
        db[collection].update_one({"_id": business["_id"]}, {"$setOnInsert": defaults}, upsert=True)
        return db[collection].find_one({"_id": business["_id"]})

    @router.patch(f"/business/{name}", name=f"update_provider_{name}")
    def patch(payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
        business = provider_business(db, user["_id"])
        db[collection].update_one({"_id": business["_id"]}, {"$set": payload}, upsert=True)
        return db[collection].find_one({"_id": business["_id"]})


singleton_settings("availability", "business_availability", {"weekly": {}, "vacation_mode": False})
singleton_settings("pricing", "business_pricing", {"starting_price": None, "callout_fee": None, "packages": []})


@router.get("/insights/{metric}")
def insights(
    metric: str,
    db: DbSession,
    user: BusinessUser,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
) -> dict:
    if metric not in {"summary", "views", "conversions", "response-time", "quotes"}:
        raise HTTPException(status_code=404, detail="Metric not found")
    business = provider_business(db, user["_id"])
    event_query: dict = {"business_id": business["_id"]}
    if date_from or date_to:
        event_query["created_at"] = {
            **({"$gte": date_from} if date_from else {}),
            **({"$lte": date_to} if date_to else {}),
        }
    views = db.analytics_events.count_documents({**event_query, "event_type": "page_view"})
    requests_count = db.customer_requests.count_documents({"category_id": business["category_id"]})
    submitted = db.provider_quotes.count_documents({"provider_id": user["_id"]})
    accepted = db.provider_quotes.count_documents({"provider_id": user["_id"], "status": "accepted"})
    return {
        "metric": metric,
        "profile_views": views,
        "quote_requests": requests_count,
        "quotes_submitted": submitted,
        "quotes_accepted": accepted,
        "view_to_request_rate": round(requests_count / views * 100, 1) if views else 0,
        "quote_win_rate": round(accepted / submitted * 100, 1) if submitted else 0,
        "average_response_minutes": 0,
        "previous_period_change": {},
    }


@router.get("/subscription")
def subscription(db: DbSession, user: BusinessUser) -> dict:
    return public(db.subscriptions.find_one({"user_id": user["_id"]})) or {"status": "none", "plan": None}


@router.post("/subscription/checkout", status_code=201)
def subscription_checkout(payload: dict = Body(...), *, db: DbSession, user: BusinessUser) -> dict:
    if db.subscriptions.find_one({"user_id": user["_id"], "status": {"$in": ["pending", "active"]}}):
        raise HTTPException(status_code=409, detail="A subscription already exists")
    item = document(
        user_id=user["_id"], plan=payload.get("plan", "pro_monthly"), status="pending", provider_session_id=new_id()
    )
    db.subscriptions.insert_one(item)
    return {"subscription_id": item["_id"], "status": "pending", "checkout_session_id": item["provider_session_id"]}


@router.post("/subscription/cancel")
def cancel_subscription(db: DbSession, user: BusinessUser) -> dict:
    item = db.subscriptions.find_one_and_update(
        {"user_id": user["_id"], "status": "active"},
        {"$set": {"status": "cancel_pending", "updated_at": utc_now()}},
        return_document=True,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Active subscription not found")
    return public(item)


@router.get("/subscription/invoices")
def invoices(db: DbSession, user: BusinessUser) -> list[dict]:
    return [public(x) for x in db.subscription_invoices.find({"user_id": user["_id"]}).sort("created_at", -1)]
