from pymongo.database import Database

from app.models import document, utc_now


def seed_reference_data(db: Database) -> None:
    if db.categories.count_documents({}) == 0:
        categories = [
            document(
                name="Home Services", slug="home-services", description="Home repair and maintenance professionals"
            ),
            document(
                name="Health & Wellness", slug="health-wellness", description="Health, fitness, and wellness providers"
            ),
            document(
                name="Professional Services",
                slug="professional-services",
                description="Business and professional expertise",
            ),
            document(name="Events", slug="events", description="Event planning and related services"),
        ]
        db.categories.insert_many(categories)
        db.faqs.insert_many(
            [
                document(
                    category_id=categories[0]["_id"],
                    question="How are providers verified?",
                    answer="Providers can submit business documents for admin verification.",
                    sort_order=0,
                ),
                document(
                    category_id=categories[1]["_id"],
                    question="Can I request a quote?",
                    answer="Yes. Sign in, choose a business, and submit your requirements.",
                    sort_order=0,
                ),
                document(
                    category_id=None,
                    question="How do I create an account?",
                    answer="Use the registration endpoint with your name, email, and password.",
                    sort_order=0,
                ),
            ]
        )
    for slug, title, content in [
        ("privacy", "Privacy Policy", "This placeholder privacy policy must be reviewed before production."),
        ("terms", "Terms of Service", "These placeholder terms must be reviewed before production."),
    ]:
        db.legal_pages.update_one(
            {"_id": slug},
            {"$setOnInsert": {"title": title, "content": content, "updated_at": utc_now()}},
            upsert=True,
        )
