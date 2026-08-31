from copy import deepcopy

from fastapi import APIRouter, Query, Request
from pymongo.errors import DuplicateKeyError

from app.api.deps import AdminUser, DbSession
from app.models import document, public, utc_now
from app.schemas.api import HomepageContent, NewsletterSubscriptionCreate

router = APIRouter()

DEFAULT_HOMEPAGE_CONTENT = {
    "hero": {
        "title": "Find Trusted Local",
        "highlight": "Businesses",
        "suffix": "Near You",
        "description": "HirePro connects you with the best local services around you.",
        "popular_searches": ["Plumber", "Electrician", "Car Repair", "Cleaning", "Home Services"],
    },
    "headings": {
        "categories": "Browse Categories",
        "featured_businesses": "Featured Local Businesses",
        "process": "How It Works",
        "testimonials": "What People Say",
    },
    "process": {
        "subtitle": "Get the best services in 3 simple steps",
        "steps": [
            {"title": "Search", "description": "Search for the service you need in your area"},
            {"title": "Choose", "description": "Compare profiles, reviews, and pricing"},
            {"title": "Hire & Relax", "description": "Book the best pro and enjoy quality service"},
        ],
    },
    "business_cta": {
        "title": "Are you a local business?",
        "description": "List your business with HirePro and reach new customers",
        "button_label": "Add Your Business",
        "button_url": "/add-your-business",
    },
    "footer": {"description": "Find trusted local businesses and services near you."},
    "seo": {
        "title": "HirePro — Trusted Local Businesses",
        "description": "Find reliable local professionals and services near you.",
    },
    "sections": {
        "categories": True,
        "featured": True,
        "process": True,
        "cta": True,
        "stats": True,
        "testimonials": True,
        "app": True,
        "newsletter": True,
    },
}


def stored_content(db: DbSession) -> dict | None:
    return db.homepage_content.find_one({"_id": "homepage"})


@router.get("/homepage-content", response_model=HomepageContent, tags=["homepage"])
def get_homepage_content(db: DbSession) -> dict:
    item = stored_content(db)
    return item["content"] if item else deepcopy(DEFAULT_HOMEPAGE_CONTENT)


@router.get("/admin/homepage-content", tags=["admin"])
def get_admin_homepage_content(db: DbSession, _: AdminUser) -> dict:
    item = stored_content(db)
    if item is None:
        return {"content": deepcopy(DEFAULT_HOMEPAGE_CONTENT), "is_default": True, "published_at": None}
    return {
        "content": item["content"],
        "is_default": item.get("is_default", False),
        "published_at": item.get("published_at"),
        "updated_at": item.get("updated_at"),
        "updated_by": item.get("updated_by"),
    }


@router.put("/admin/homepage-content", response_model=HomepageContent, tags=["admin"])
def publish_homepage_content(
    payload: HomepageContent, request: Request, db: DbSession, admin: AdminUser
) -> dict:
    now = utc_now()
    content = payload.model_dump()
    db.homepage_content.update_one(
        {"_id": "homepage"},
        {
            "$set": {
                "content": content,
                "is_default": False,
                "published_at": now,
                "updated_at": now,
                "updated_by": admin["_id"],
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    db.audit_logs.insert_one(
        document(
            admin_id=admin["_id"],
            action="homepage_content_published",
            target_type="homepage_content",
            target_id="homepage",
            metadata={},
            ip_address=request.client.host if request.client else None,
        )
    )
    return content


@router.post("/admin/homepage-content/reset", response_model=HomepageContent, tags=["admin"])
def reset_homepage_content(request: Request, db: DbSession, admin: AdminUser) -> dict:
    content = HomepageContent.model_validate(DEFAULT_HOMEPAGE_CONTENT)
    publish_homepage_content(content, request, db, admin)
    db.homepage_content.update_one({"_id": "homepage"}, {"$set": {"is_default": True}})
    return content.model_dump()


@router.post("/admin/homepage-content/preview", response_model=HomepageContent, tags=["admin"])
def preview_homepage_content(payload: HomepageContent, _: AdminUser) -> dict:
    """Validate and return content without persisting it."""
    return payload.model_dump()


@router.get("/homepage/stats", tags=["homepage"])
def homepage_stats(db: DbSession) -> dict[str, int]:
    return {
        "businesses": db.businesses.count_documents({"is_active": True}),
        "verified_businesses": db.businesses.count_documents({"is_active": True, "is_verified": True}),
        "categories": db.categories.count_documents({}),
        "reviews": db.reviews.count_documents({"is_approved": True}),
        "cities": len(db.businesses.distinct("city", {"is_active": True})),
    }


@router.get("/testimonials", tags=["homepage"])
def testimonials(
    db: DbSession, featured: bool | None = None, limit: int = Query(3, ge=1, le=20)
) -> list[dict]:
    query: dict = {"is_approved": True}
    if featured is not None:
        query["is_featured"] = featured
    results = []
    for review in db.reviews.find(query).sort([("rating", -1), ("created_at", -1)]).limit(limit):
        item = public(review)
        user = db.users.find_one({"_id": review.get("user_id")}, {"full_name": 1, "profile_image_url": 1})
        business = db.businesses.find_one({"_id": review.get("business_id")}, {"name": 1, "slug": 1})
        item["author"] = public(user) if user else None
        item["business"] = public(business) if business else None
        results.append(item)
    return results


@router.post("/newsletter/subscriptions", status_code=201, tags=["homepage"])
def subscribe_newsletter(payload: NewsletterSubscriptionCreate, db: DbSession) -> dict[str, str]:
    email = payload.email.strip().lower()
    item = document(email=email, status="subscribed", subscribed_at=utc_now())
    try:
        db.newsletter_subscriptions.insert_one(item)
    except DuplicateKeyError:
        db.newsletter_subscriptions.update_one(
            {"email": email}, {"$set": {"status": "subscribed", "subscribed_at": utc_now(), "updated_at": utc_now()}}
        )
        existing = db.newsletter_subscriptions.find_one({"email": email})
        return {"id": str(existing["_id"]), "status": "subscribed"}
    return {"id": item["_id"], "status": "subscribed"}
