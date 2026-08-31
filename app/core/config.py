from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HirePro API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    docs_enabled: bool = True
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    cors_origin_regex: str = r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$"
    database_url: str = "mongodb://localhost:27017"
    database_name: str = "HirePro"
    jwt_secret: str = "change-me-in-production-use-32-bytes"
    access_token_minutes: int = 60 * 24
    admin_email: str = "admin@hirepro.com"
    admin_password: str = ""
    payment_webhook_secret: str = "change-payment-webhook-secret"
    upload_directory: str = "uploads"
    maximum_upload_bytes: int = 5 * 1024 * 1024
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_folder: str = "hirepro"

    @property
    def cloudinary_enabled(self) -> bool:
        return bool(self.cloudinary_cloud_name and self.cloudinary_api_key and self.cloudinary_api_secret)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
