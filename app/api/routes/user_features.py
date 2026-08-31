from fastapi import APIRouter, HTTPException

from app.api.deps import BusinessUser, CurrentUser, CustomerUser, DbSession
from app.models import document, new_id, public, utc_now
from app.schemas.api import (
    BusinessOut,
    NotificationOut,
    OnboardingOut,
    OnboardingUpdate,
    PreferenceOut,
    PreferenceUpdate,
    QuoteCreate,
    QuoteOut,
    SubscriptionCreate,
)

router = APIRouter()


@router.post("/quotes", response_model=QuoteOut, status_code=201, tags=["quotes"])
def submit_quote(payload: QuoteCreate, db: DbSession, user: CustomerUser) -> dict:
    business = db.businesses.find_one({"_id": payload.business_id, "is_active": True})
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    quote = document(user_id=user["_id"], status="submitted", **payload.model_dump())
    db.quote_requests.insert_one(quote)
    db.notifications.insert_one(
        document(
            user_id=business["owner_id"],
            title="New quote request",
            message=f"A quote was requested for {business['name']}",
            is_read=False,
        )
    )
    return public(quote)


@router.get("/quotes", response_model=list[QuoteOut], tags=["quotes"])
def user_quotes(db: DbSession, user: CurrentUser) -> list[dict]:
    role = user.get("role", "customer")
    if role == "customer":
        query = {"user_id": user["_id"]}
    elif role == "business":
        business_ids = [x["_id"] for x in db.businesses.find({"owner_id": user["_id"]}, {"_id": 1})]
        query = {"business_id": {"$in": business_ids}}
    else:
        raise HTTPException(status_code=403, detail="Unsupported account role")
    return [public(x) for x in db.quote_requests.find(query).sort("created_at", -1)]


@router.get("/favorites", response_model=list[BusinessOut], tags=["favorites"])
def favorites(db: DbSession, user: CustomerUser) -> list[dict]:
    ids = [x["business_id"] for x in db.favorites.find({"user_id": user["_id"]})]
    return [public(x) for x in db.businesses.find({"_id": {"$in": ids}, "is_active": True})]


def get_or_create_onboarding(db: DbSession, user_id: str) -> dict:
    db.onboarding_progress.update_one(
        {"_id": user_id},
        {
            "$setOnInsert": {
                "current_step": 1,
                "data": {},
                "completed": False,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        },
        upsert=True,
    )
    return db.onboarding_progress.find_one({"_id": user_id})


@router.get("/onboarding", response_model=OnboardingOut, tags=["onboarding"])
def onboarding_status(db: DbSession, user: BusinessUser) -> dict:
    item = get_or_create_onboarding(db, user["_id"])
    return {**item, "user_id": item["_id"]}


@router.put("/onboarding", response_model=OnboardingOut, tags=["onboarding"])
def save_onboarding(payload: OnboardingUpdate, db: DbSession, user: BusinessUser) -> dict:
    current = get_or_create_onboarding(db, user["_id"])
    values = {
        "current_step": payload.current_step,
        "data": {**current["data"], **payload.data},
        "completed": payload.completed,
        "updated_at": utc_now(),
    }
    db.onboarding_progress.update_one({"_id": user["_id"]}, {"$set": values})
    return {"user_id": user["_id"], **values}


@router.post("/subscriptions/pro", status_code=201, tags=["subscriptions"])
def create_subscription(payload: SubscriptionCreate, db: DbSession, user: BusinessUser) -> dict[str, str]:
    if db.subscriptions.find_one({"user_id": user["_id"], "status": {"$in": ["pending", "active"]}}):
        raise HTTPException(status_code=409, detail="A subscription already exists")
    session_id = new_id()
    item = document(user_id=user["_id"], plan=payload.plan, status="pending", provider_session_id=session_id)
    db.subscriptions.insert_one(item)
    return {"subscription_id": item["_id"], "status": item["status"], "checkout_session_id": session_id}


@router.get("/notifications", response_model=list[NotificationOut], tags=["notifications"])
def notifications(db: DbSession, user: CurrentUser) -> list[dict]:
    return [public(x) for x in db.notifications.find({"user_id": user["_id"]}).sort("created_at", -1)]


@router.patch("/notifications/{notification_id}/read", response_model=NotificationOut, tags=["notifications"])
def mark_notification_read(notification_id: str, db: DbSession, user: CurrentUser) -> dict:
    item = db.notifications.find_one_and_update(
        {"_id": notification_id, "user_id": user["_id"]}, {"$set": {"is_read": True}}, return_document=True
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return public(item)


@router.patch("/notifications/read-all", tags=["notifications"])
def mark_all_read(db: DbSession, user: CurrentUser) -> dict[str, int]:
    result = db.notifications.update_many({"user_id": user["_id"], "is_read": False}, {"$set": {"is_read": True}})
    return {"updated": result.modified_count}


def get_or_create_preferences(db: DbSession, user_id: str) -> dict:
    db.user_preferences.update_one(
        {"_id": user_id},
        {
            "$setOnInsert": {
                "email_notifications": True,
                "push_notifications": True,
                "theme": "system",
                "language": "en",
            }
        },
        upsert=True,
    )
    return db.user_preferences.find_one({"_id": user_id})


@router.get("/preferences", response_model=PreferenceOut, tags=["user-preferences"])
def get_preferences(db: DbSession, user: CurrentUser) -> dict:
    return get_or_create_preferences(db, user["_id"])


@router.put("/preferences", response_model=PreferenceOut, tags=["user-preferences"])
def update_preferences(payload: PreferenceUpdate, db: DbSession, user: CurrentUser) -> dict:
    get_or_create_preferences(db, user["_id"])
    db.user_preferences.update_one({"_id": user["_id"]}, {"$set": payload.model_dump()})
    return db.user_preferences.find_one({"_id": user["_id"]})
