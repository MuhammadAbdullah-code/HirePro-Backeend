import logging
from collections.abc import Generator

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

from app.core.config import settings

logger = logging.getLogger("uvicorn.error")
client: MongoClient | None = None


def get_database() -> Database:
    global client
    if client is None:
        # Configure connection with better pooling and timeout settings
        client = MongoClient(
            settings.database_url,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=30000,
            maxPoolSize=50,
            minPoolSize=10,
            maxIdleTimeMS=45000,
            waitQueueTimeoutMS=10000,
            retryWrites=True,
            retryReads=True,
            # Keep connections warm
            maxConnecting=2,
        )
        # Force immediate connection to avoid first-request delay
        client.admin.command("ping")
        logger.info("Connected to MongoDB database '%s'", settings.database_name)
    return client[settings.database_name]


def get_db() -> Generator[Database, None, None]:
    yield get_database()


def create_indexes(db: Database | None = None) -> None:
    mongo = db if db is not None else get_database()
    mongo.users.create_index("email", unique=True)
    mongo.categories.create_index("slug", unique=True)
    mongo.businesses.create_index("slug", unique=True)
    mongo.businesses.create_index([("is_verified", DESCENDING), ("name", ASCENDING)])
    mongo.favorites.create_index([("user_id", ASCENDING), ("business_id", ASCENDING)], unique=True)
    mongo.reviews.create_index([("user_id", ASCENDING), ("business_id", ASCENDING)], unique=True)
    mongo.review_helpful.create_index([("review_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
    mongo.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    mongo.revoked_tokens.create_index("expires_at", expireAfterSeconds=0)
    mongo.refresh_tokens.create_index("token_hash", unique=True)
    mongo.refresh_tokens.create_index("expires_at", expireAfterSeconds=0)
    mongo.newsletter_subscriptions.create_index("email", unique=True)
    mongo.customer_requests.create_index([("user_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)])
    mongo.provider_quotes.create_index([("provider_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)])


def migrate_database(db: Database | None = None) -> dict[str, int]:
    """Apply idempotent MongoDB data migrations required by the current application."""
    mongo = db if db is not None else get_database()
    legacy = mongo.users.update_many({"role": "provider"}, {"$set": {"role": "business"}})
    missing = mongo.users.update_many(
        {"$or": [{"role": {"$exists": False}}, {"role": None}]},
        {"$set": {"role": "customer"}},
    )
    return {"provider_to_business": legacy.modified_count, "defaulted_to_customer": missing.modified_count}


def close_database() -> None:
    global client
    if client is not None:
        client.close()
        client = None
