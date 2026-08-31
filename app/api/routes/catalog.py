import math
import re
from hashlib import sha256

from fastapi import APIRouter, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from app.api.deps import BusinessUser, CustomerUser, DbSession
from app.models import document, public, utc_now
from app.schemas.api import (
    BusinessCreate,
    BusinessOut,
    BusinessUpdate,
    CategoryDetail,
    CategoryOut,
    ContactCreate,
    GeocodeRequest,
    ReviewCreate,
    ReviewOut,
)

router = APIRouter()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def business_or_404(db: DbSession, business_id: str) -> dict:
    business = db.businesses.find_one({"_id": business_id, "is_active": True})
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.get("/categories", response_model=list[CategoryOut], tags=["categories"])
def list_categories(db: DbSession, limit: int = Query(100, ge=1, le=100)) -> list[dict]:
    return [public(x) for x in db.categories.find().sort("name", 1).limit(limit)]


@router.get("/categories/{slug}", response_model=CategoryDetail, tags=["categories"])
def category_detail(slug: str, db: DbSession) -> dict:
    category = db.categories.find_one({"slug": slug})
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    result = public(category)
    result["faqs"] = [public(x) for x in db.faqs.find({"category_id": category["_id"]}).sort("sort_order", 1)]
    return result


@router.get("/businesses", response_model=list[BusinessOut], tags=["businesses"])
def search_businesses(
    db: DbSession,
    q: str | None = None,
    category_id: str | None = None,
    city: str | None = None,
    verified: bool | None = None,
    featured: bool | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    filters: dict = {"is_active": True}
    if q:
        term = q.strip()
        filters["$or"] = [
            {"name": {"$regex": re.escape(term), "$options": "i"}},
            {"description": {"$regex": re.escape(term), "$options": "i"}},
        ]
        db.popular_searches.update_one({"_id": term.lower()}, {"$inc": {"count": 1}}, upsert=True)
    if category_id:
        filters["category_id"] = category_id
    if city:
        filters["city"] = {"$regex": f"^{re.escape(city.strip())}$", "$options": "i"}
    if verified is not None:
        filters["is_verified"] = verified
    if featured is not None:
        filters["is_featured"] = featured
    cursor = db.businesses.find(filters).sort([("is_verified", -1), ("name", 1)]).skip(offset).limit(limit)
    return [public(x) for x in cursor]


@router.get("/businesses/{business_id}", response_model=BusinessOut, tags=["businesses"])
def business_detail(business_id: str, db: DbSession) -> dict:
    business_or_404(db, business_id)
    item = db.businesses.find_one_and_update(
        {"_id": business_id}, {"$inc": {"view_count": 1}, "$set": {"updated_at": utc_now()}}, return_document=True
    )
    return public(item)


@router.post("/businesses", response_model=BusinessOut, status_code=201, tags=["businesses"])
def create_business(payload: BusinessCreate, db: DbSession, user: BusinessUser) -> dict:
    if db.categories.find_one({"_id": payload.category_id}) is None:
        raise HTTPException(status_code=400, detail="Invalid category")
    base_slug = slugify(payload.name)
    slug, counter = base_slug, 2
    while db.businesses.find_one({"slug": slug}):
        slug, counter = f"{base_slug}-{counter}", counter + 1
    item = document(
        owner_id=user["_id"], slug=slug, is_verified=False, is_active=True, view_count=0, **payload.model_dump()
    )
    db.businesses.insert_one(item)
    return public(item)


@router.patch("/businesses/{business_id}", response_model=BusinessOut, tags=["businesses"])
def update_business(business_id: str, payload: BusinessUpdate, db: DbSession, user: BusinessUser) -> dict:
    business = business_or_404(db, business_id)
    if business["owner_id"] != user["_id"]:
        raise HTTPException(status_code=403, detail="You do not own this business")
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    if values:
        values["updated_at"] = utc_now()
        db.businesses.update_one({"_id": business_id}, {"$set": values})
    return public(db.businesses.find_one({"_id": business_id}))


@router.post("/businesses/{business_id}/favorite", tags=["businesses"])
def toggle_favorite(business_id: str, db: DbSession, user: CustomerUser) -> dict[str, bool]:
    business_or_404(db, business_id)
    key = {"user_id": user["_id"], "business_id": business_id}
    existing = db.favorites.find_one(key)
    if existing:
        db.favorites.delete_one({"_id": existing["_id"]})
        return {"is_favorite": False}
    db.favorites.insert_one(document(**key))
    return {"is_favorite": True}


@router.get("/businesses/{business_id}/share", tags=["businesses"])
def share_business(business_id: str, db: DbSession) -> dict[str, str]:
    return {"url": f"/businesses/{business_or_404(db, business_id)['slug']}"}


@router.get("/businesses/{business_id}/reviews", response_model=list[ReviewOut], tags=["reviews"])
def list_reviews(business_id: str, db: DbSession) -> list[dict]:
    business_or_404(db, business_id)
    return [
        public(x) for x in db.reviews.find({"business_id": business_id, "is_approved": True}).sort("created_at", -1)
    ]


@router.post("/businesses/{business_id}/reviews", response_model=ReviewOut, status_code=201, tags=["reviews"])
def submit_review(business_id: str, payload: ReviewCreate, db: DbSession, user: CustomerUser) -> dict:
    business_or_404(db, business_id)
    item = document(
        user_id=user["_id"], business_id=business_id, helpful_count=0, is_approved=True, **payload.model_dump()
    )
    try:
        db.reviews.insert_one(item)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="You already reviewed this business") from exc
    return public(item)


@router.post("/reviews/{review_id}/helpful", tags=["reviews"])
def mark_helpful(review_id: str, db: DbSession, user: CustomerUser) -> dict[str, int]:
    if db.reviews.find_one({"_id": review_id}) is None:
        raise HTTPException(status_code=404, detail="Review not found")
    try:
        db.review_helpful.insert_one(document(review_id=review_id, user_id=user["_id"]))
        db.reviews.update_one({"_id": review_id}, {"$inc": {"helpful_count": 1}})
    except DuplicateKeyError:
        pass
    return {"helpful_count": db.reviews.find_one({"_id": review_id})["helpful_count"]}


@router.get("/search/autocomplete", tags=["search"])
def autocomplete(db: DbSession, q: str = Query(min_length=2)) -> dict[str, list[str]]:
    rows = db.businesses.find(
        {"name": {"$regex": f"^{re.escape(q)}", "$options": "i"}, "is_active": True}, {"name": 1}
    ).limit(10)
    return {"suggestions": [x["name"] for x in rows]}


@router.get("/search/popular", tags=["search"])
def popular_searches(db: DbSession) -> dict[str, list[str]]:
    return {"searches": [x["_id"] for x in db.popular_searches.find().sort("count", -1).limit(10)]}


@router.post("/contact", status_code=201, tags=["contact"])
def contact(payload: ContactCreate, db: DbSession) -> dict[str, str]:
    item = document(status="new", **payload.model_dump())
    db.contact_messages.insert_one(item)
    return {"id": item["_id"], "status": "received"}


@router.get("/contact/faqs", response_model=list[dict], tags=["contact"])
def global_faqs(db: DbSession) -> list[dict]:
    return [
        {"question": x["question"], "answer": x["answer"]}
        for x in db.faqs.find({"category_id": None}).sort("sort_order", 1)
    ]


@router.get("/locations/cities", tags=["locations"])
def cities(db: DbSession) -> dict[str, list[str]]:
    return {"cities": sorted(db.businesses.distinct("city"))}


@router.post("/locations/geocode", tags=["locations"])
def geocode(payload: GeocodeRequest) -> dict[str, float | str]:
    digest = sha256(payload.address.strip().lower().encode()).digest()
    return {
        "address": payload.address,
        "latitude": round(24.0 + int.from_bytes(digest[:2]) / 65535 * 13, 6),
        "longitude": round(61.0 + int.from_bytes(digest[2:4]) / 65535 * 16, 6),
    }


@router.get("/locations/nearby", response_model=list[BusinessOut], tags=["locations"])
def nearby(db: DbSession, latitude: float, longitude: float, radius_km: float = Query(10, gt=0, le=200)) -> list[dict]:
    result = []
    for item in db.businesses.find({"latitude": {"$ne": None}, "longitude": {"$ne": None}, "is_active": True}):
        distance = math.sqrt((item["latitude"] - latitude) ** 2 + (item["longitude"] - longitude) ** 2) * 111
        if distance <= radius_km:
            result.append((distance, item))
    return [public(x) for _, x in sorted(result, key=lambda pair: pair[0])]


@router.get("/legal/{slug}", tags=["static-content"])
def legal_page(slug: str, db: DbSession) -> dict[str, str]:
    page = db.legal_pages.find_one({"_id": slug})
    if page is None:
        raise HTTPException(status_code=404, detail="Legal page not found")
    return {"slug": slug, "title": page["title"], "content": page["content"]}
