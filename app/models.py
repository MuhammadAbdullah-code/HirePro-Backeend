from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


def document(**values: Any) -> dict[str, Any]:
    now = utc_now()
    return {"_id": values.pop("id", new_id()), "created_at": now, "updated_at": now, **values}


def public(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result = dict(value)
    if "_id" in result:
        result["id"] = str(result.pop("_id"))
    return result
