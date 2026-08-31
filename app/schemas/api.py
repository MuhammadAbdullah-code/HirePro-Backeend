from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)
    role: Literal["customer", "business"]


class LoginRequest(BaseModel):
    email: str
    password: str


class OAuthRequest(BaseModel):
    provider: Literal["google", "facebook", "apple"]
    provider_token: str = Field(min_length=8)
    email: str
    full_name: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: str
    email: str
    full_name: str
    is_admin: bool
    role: Literal["customer", "business"] = "customer"
    phone: str | None = None
    profile_image_url: str | None = None
    created_at: datetime


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = Field(default=None, min_length=5, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    profile_image_url: str | None = Field(default=None, max_length=2048)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def require_password_for_sensitive_changes(self) -> "ProfileUpdate":
        if self.new_password is not None and not self.current_password:
            raise ValueError("current_password is required to change password")
        return self


class FAQOut(ORMModel):
    id: str
    question: str
    answer: str
    sort_order: int


class CategoryOut(ORMModel):
    id: str
    name: str
    slug: str
    description: str


class CategoryDetail(CategoryOut):
    faqs: list[FAQOut]


class BusinessCreate(BaseModel):
    category_id: str
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=10)
    city: str
    address: str = ""
    phone: str = ""
    website: str = ""
    latitude: float | None = None
    longitude: float | None = None


class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, min_length=10)
    city: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class BusinessOut(ORMModel):
    id: str
    owner_id: str
    category_id: str
    name: str
    slug: str
    description: str
    city: str
    address: str
    phone: str
    website: str
    latitude: float | None = None
    longitude: float | None = None
    is_verified: bool
    is_active: bool
    view_count: int
    created_at: datetime


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    title: str = Field(default="", max_length=120)
    comment: str = Field(min_length=3)


class ReviewOut(ORMModel):
    id: str
    user_id: str
    business_id: str
    rating: int
    title: str
    comment: str
    helpful_count: int
    created_at: datetime


class QuoteCreate(BaseModel):
    business_id: str
    details: str = Field(min_length=10)
    budget: float | None = Field(default=None, ge=0)


class QuoteOut(ORMModel):
    id: str
    business_id: str
    details: str
    budget: float | None = None
    status: str
    created_at: datetime


class ContactCreate(BaseModel):
    name: str
    email: str
    subject: str
    message: str = Field(min_length=10)


class OnboardingUpdate(BaseModel):
    current_step: int = Field(ge=1)
    data: dict[str, Any] = Field(default_factory=dict)
    completed: bool = False


class OnboardingOut(ORMModel):
    user_id: str
    current_step: int
    data: dict[str, Any]
    completed: bool


class SubscriptionCreate(BaseModel):
    plan: Literal["pro_monthly", "pro_yearly"] = "pro_monthly"


class AnalyticsCreate(BaseModel):
    business_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NotificationOut(ORMModel):
    id: str
    title: str
    message: str
    is_read: bool
    created_at: datetime


class PreferenceUpdate(BaseModel):
    email_notifications: bool = True
    push_notifications: bool = True
    theme: Literal["light", "dark", "system"] = "system"
    language: str = Field(default="en", min_length=2, max_length=10)


class PreferenceOut(ORMModel):
    email_notifications: bool
    push_notifications: bool
    theme: str
    language: str


class GeocodeRequest(BaseModel):
    address: str = Field(min_length=3)


class ModerationUpdate(BaseModel):
    approved: bool


class VerificationUpdate(BaseModel):
    verified: bool


class HomepageHero(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    highlight: str = Field(min_length=1, max_length=80)
    suffix: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    popular_searches: list[str] = Field(default_factory=list, max_length=20)


class HomepageHeadings(BaseModel):
    categories: str = Field(min_length=1, max_length=160)
    featured_businesses: str = Field(min_length=1, max_length=160)
    process: str = Field(min_length=1, max_length=160)
    testimonials: str = Field(min_length=1, max_length=160)


class HomepageProcessStep(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=300)


class HomepageProcess(BaseModel):
    subtitle: str = Field(min_length=1, max_length=300)
    steps: list[HomepageProcessStep] = Field(min_length=1, max_length=10)


class HomepageBusinessCta(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    button_label: str = Field(min_length=1, max_length=80)
    button_url: str = Field(min_length=1, max_length=2048)


class HomepageFooter(BaseModel):
    description: str = Field(min_length=1, max_length=500)


class HomepageSeo(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)


class HomepageSections(BaseModel):
    categories: bool = True
    featured: bool = True
    process: bool = True
    cta: bool = True
    stats: bool = True
    testimonials: bool = True
    app: bool = True
    newsletter: bool = True


class HomepageContent(BaseModel):
    hero: HomepageHero
    headings: HomepageHeadings
    process: HomepageProcess
    business_cta: HomepageBusinessCta
    footer: HomepageFooter
    seo: HomepageSeo
    sections: HomepageSections


class NewsletterSubscriptionCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class MarketplaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_registration: bool = True
    provider_registration: bool = True
    require_verification: bool = True
    auto_publish_verified: bool = True
    max_businesses_per_provider: int = Field(default=1, ge=1, le=100)
    max_active_requests: int = Field(default=10, ge=1, le=1000)
    quote_expiry_days: int = Field(default=7, ge=1, le=365)
    max_quotes_per_request: int = Field(default=5, ge=1, le=100)
    request_expiry_days: int = Field(default=30, ge=1, le=365)
    service_radius_km: int = Field(default=50, ge=1, le=1000)
    min_quote_amount: float = Field(default=0, ge=0)
    max_quote_amount: float = Field(default=1_000_000, ge=0)
    allow_review_edits: bool = True
    review_edit_hours: int = Field(default=24, ge=0, le=720)

    @model_validator(mode="after")
    def validate_quote_range(self) -> "MarketplaceSettings":
        if self.max_quote_amount < self.min_quote_amount:
            raise ValueError("max_quote_amount must be greater than or equal to min_quote_amount")
        if self.quote_expiry_days > self.request_expiry_days:
            raise ValueError("quote_expiry_days cannot exceed request_expiry_days")
        return self


class GeneralAdminSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_name: str = Field(default="HirePro", min_length=1, max_length=120)
    support_email: str = Field(default="support@hirepro.com", min_length=5, max_length=255)
    support_phone: str = Field(default="", max_length=30)
    business_address: str = Field(default="", max_length=500)
    country: str = Field(default="Pakistan", min_length=2, max_length=100)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Karachi", min_length=1, max_length=100)
    language: str = Field(default="English", min_length=2, max_length=50)
    website_url: str = Field(default="", max_length=2048)
    maintenance_contact: str = Field(default="", max_length=255)
    copyright_text: str = Field(default="© 2026 HirePro. All rights reserved.", max_length=500)
    logo_url: str = Field(default="", max_length=2048)
    favicon_url: str = Field(default="", max_length=2048)

    @field_validator("support_email")
    @classmethod
    def validate_support_email(cls, value: str) -> str:
        if not __import__("re").fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("support_email must be a valid email address")
        return value

    @field_validator("support_phone")
    @classmethod
    def validate_support_phone(cls, value: str) -> str:
        if value and not __import__("re").fullmatch(r"[+()\-\s\d]{7,30}", value):
            raise ValueError("support_phone must be a valid phone number")
        return value

    @field_validator("website_url", "logo_url", "favicon_url")
    @classmethod
    def validate_public_url(cls, value: str) -> str:
        if value and not (value.startswith("http://") or value.startswith("https://") or value.startswith("/")):
            raise ValueError("URL must be absolute HTTP(S) or root-relative")
        return value


class TrustSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_mode: Literal["manual", "automatic", "hybrid"] = "manual"
    required_documents: str = Field(default="Identity document, Business registration", max_length=1000)
    review_moderation: Literal["flagged", "all", "automatic"] = "flagged"
    flag_suspicious_reviews: bool = True
    blocked_keywords: str = Field(default="", max_length=5000)
    reports_before_hide: int = Field(default=3, ge=1, le=100)
    require_action_reason: bool = True
    allow_appeals: bool = True
    appeal_deadline_days: int = Field(default=7, ge=1, le=365)
    fraud_threshold: int = Field(default=70, ge=0, le=100)
    duplicate_detection: bool = True
    hide_expired_documents: bool = True
    default_suspension_days: int = Field(default=30, ge=1, le=3650)
    require_policy_approval: bool = True


class CommunicationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_name: str = Field(default="HirePro", min_length=1, max_length=120)
    sender_email: str = Field(default="notifications@hirepro.com", min_length=5, max_length=255)
    reply_to_email: str = Field(default="support@hirepro.com", min_length=5, max_length=255)
    transactional_email: bool = True
    marketing_email: bool = False
    notify_registration: bool = True
    notify_verification: bool = True
    notify_requests: bool = True
    notify_quotes: bool = True
    notify_reviews: bool = True
    notify_support: bool = True
    notify_expiry: bool = True
    push_notifications: bool = True
    sms_notifications: bool = False
    notification_recipients: str = Field(default="", max_length=2000)

    @field_validator("sender_email", "reply_to_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not __import__("re").fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("A valid email address is required")
        return value


class SecurityAdminSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_mfa: bool = True
    session_minutes: int = Field(default=60, ge=5, le=43200)
    max_login_attempts: int = Field(default=5, ge=1, le=20)
    lockout_minutes: int = Field(default=30, ge=1, le=1440)
    password_min_length: int = Field(default=10, ge=8, le=128)
    require_uppercase: bool = True
    require_number: bool = True
    require_symbol: bool = True
    password_expiry_days: int = Field(default=0, ge=0, le=3650)
    allowed_ips: str = Field(default="", max_length=5000)
    rate_limit_per_minute: int = Field(default=120, ge=1, le=100000)
    security_recipients: str = Field(default="security@hirepro.com", max_length=2000)
    cors_origins: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("allowed_ips")
    @classmethod
    def validate_allowed_ips(cls, value: str) -> str:
        for address in (item.strip() for item in value.split(",")):
            if address:
                __import__("ipaddress").ip_address(address)
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, values: list[str]) -> list[str]:
        if any(not value.startswith(("http://", "https://")) for value in values):
            raise ValueError("CORS origins must use HTTP or HTTPS")
        return values


class IntegrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connected: bool = False
    environment: Literal["test", "production"] = "test"
    last_success: datetime | None = None
    last_failure: datetime | None = None
    credential_expires_at: datetime | None = None
    updated_at: datetime | None = None
    credentials: dict[str, Any] = Field(default_factory=dict, exclude=True)


class IntegrationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: IntegrationStatus = Field(
        default_factory=lambda: IntegrationStatus(connected=True, environment="production")
    )
    storage: IntegrationStatus = Field(
        default_factory=lambda: IntegrationStatus(connected=True, environment="production")
    )
    maps: IntegrationStatus = Field(default_factory=IntegrationStatus)
    payments: IntegrationStatus = Field(default_factory=IntegrationStatus)
    analytics: IntegrationStatus = Field(
        default_factory=lambda: IntegrationStatus(connected=True, environment="production")
    )
    sms: IntegrationStatus = Field(default_factory=IntegrationStatus)


class FeatureFlagSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    rollout: int = Field(ge=0, le=100)
    roles: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=1000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "FeatureFlagSettings":
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class FeatureControlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_requests: FeatureFlagSettings = Field(
        default_factory=lambda: FeatureFlagSettings(enabled=True, rollout=100, roles="customer,provider")
    )
    provider_quotes: FeatureFlagSettings = Field(
        default_factory=lambda: FeatureFlagSettings(enabled=True, rollout=100, roles="provider")
    )
    reviews: FeatureFlagSettings = Field(
        default_factory=lambda: FeatureFlagSettings(enabled=True, rollout=100, roles="customer")
    )
    favorites: FeatureFlagSettings = Field(
        default_factory=lambda: FeatureFlagSettings(enabled=True, rollout=100, roles="customer")
    )
    comparison: FeatureFlagSettings = Field(
        default_factory=lambda: FeatureFlagSettings(enabled=True, rollout=100, roles="customer")
    )
    newsletter: FeatureFlagSettings = Field(
        default_factory=lambda: FeatureFlagSettings(enabled=True, rollout=100, roles="public")
    )
    subscriptions: FeatureFlagSettings = Field(
        default_factory=lambda: FeatureFlagSettings(enabled=False, rollout=0, roles="provider")
    )
    realtime_messaging: FeatureFlagSettings = Field(
        default_factory=lambda: FeatureFlagSettings(enabled=False, rollout=0, roles="customer,provider")
    )


class SystemHealthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maintenance_mode: bool = False
    maintenance_title: str = Field(default="We’ll be back shortly", max_length=160)
    maintenance_message: str = Field(default="HirePro is undergoing scheduled maintenance.", max_length=1000)
    expected_restoration: str = Field(default="", max_length=100)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    admin_bypass: bool = True
    allowed_ips: str = Field(default="", max_length=5000)
    status_page_url: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def validate_schedule(self) -> "SystemHealthSettings":
        if self.scheduled_start and self.scheduled_end and self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be later than scheduled_start")
        return self


class PrivacySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_retention_days: int = Field(default=2555, ge=1, le=36500)
    analytics_retention_days: int = Field(default=730, ge=1, le=36500)
    deleted_account_grace_days: int = Field(default=30, ge=0, le=365)
    cookie_consent: bool = True
    marketing_consent: bool = True
    anonymize_expired: bool = True
    export_format: Literal["json", "csv"] = "json"
