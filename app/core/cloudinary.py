from time import time
from typing import Any

import cloudinary
import cloudinary.uploader
from cloudinary.utils import api_sign_request

from app.core.config import settings


def configure_cloudinary() -> None:
    """Configure the Cloudinary SDK from application settings."""
    if settings.cloudinary_enabled:
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )


def upload_bytes(content: bytes, *, public_id: str, resource_type: str) -> dict[str, Any]:
    configure_cloudinary()
    return cloudinary.uploader.upload(
        content,
        public_id=public_id,
        folder=settings.cloudinary_folder,
        resource_type=resource_type,
        overwrite=False,
    )


def delete_asset(public_id: str, *, resource_type: str) -> None:
    configure_cloudinary()
    cloudinary.uploader.destroy(public_id, resource_type=resource_type, invalidate=True)


def signed_upload_parameters() -> dict[str, str | int]:
    """Return short-lived parameters for a direct browser-to-Cloudinary upload."""
    configure_cloudinary()
    timestamp = int(time())
    parameters: dict[str, str | int] = {
        "timestamp": timestamp,
        "folder": settings.cloudinary_folder,
    }
    signature = api_sign_request(parameters, settings.cloudinary_api_secret)
    return {
        **parameters,
        "signature": signature,
        "api_key": settings.cloudinary_api_key,
        "cloud_name": settings.cloudinary_cloud_name,
        "upload_url": (f"https://api.cloudinary.com/v1_1/{settings.cloudinary_cloud_name}/auto/upload"),
    }
