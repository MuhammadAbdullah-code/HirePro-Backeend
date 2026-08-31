import argparse

from app.core.security import hash_password
from app.db import create_indexes, get_database
from app.models import new_id, utc_now


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote a HirePro administrator")
    parser.add_argument("email")
    parser.add_argument("--name", default="Administrator")
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    database = get_database()
    create_indexes(database)
    email = args.email.strip().lower()
    values = {
        "full_name": args.name,
        "password_hash": hash_password(args.password),
        "is_admin": True,
        "is_active": True,
        "updated_at": utc_now(),
    }
    database.users.update_one(
        {"email": email},
        {
            "$set": values,
            "$setOnInsert": {
                "_id": new_id(),
                "email": email,
                "oauth_provider": None,
                "role": "business",
                "created_at": utc_now(),
            },
        },
        upsert=True,
    )
    print(f"Admin ready: {email}")


if __name__ == "__main__":
    main()
