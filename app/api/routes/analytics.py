from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession, OptionalUser
from app.models import document
from app.schemas.api import AnalyticsCreate

router = APIRouter(prefix="/analytics")


def record_event(event_type: str, payload: AnalyticsCreate, db: DbSession, user: OptionalUser) -> dict[str, str]:
    if payload.business_id and not db.businesses.find_one({"_id": payload.business_id}):
        raise HTTPException(status_code=404, detail="Business not found")
    event = document(
        event_type=event_type,
        business_id=payload.business_id,
        user_id=user["_id"] if user else None,
        metadata_json=payload.metadata,
    )
    db.analytics_events.insert_one(event)
    return {"event_id": event["_id"], "status": "recorded"}


@router.post("/page-views", status_code=201)
def page_view(payload: AnalyticsCreate, db: DbSession, user: OptionalUser) -> dict[str, str]:
    return record_event("page_view", payload, db, user)


@router.post("/business-clicks", status_code=201)
def business_click(payload: AnalyticsCreate, db: DbSession, user: OptionalUser) -> dict[str, str]:
    return record_event("business_click", payload, db, user)


@router.post("/quote-conversions", status_code=201)
def quote_conversion(payload: AnalyticsCreate, db: DbSession, user: OptionalUser) -> dict[str, str]:
    return record_event("quote_conversion", payload, db, user)
