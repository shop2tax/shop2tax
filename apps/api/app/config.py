"""Application configuration using Pydantic Settings."""

from functools import lru_cache

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Environment (development, staging, production)
    environment: str = "development"

    # Database (required — presence enforced in the validator below)
    database_url: str = ""

    # OAuth credentials (used to detect Local Mode)
    google_client_id: str = ""

    @computed_field
    @property
    def local_mode(self) -> bool:
        """Auto-detect: No Google OAuth credentials → Local Mode (D5: einheitliches Signal)."""
        return not bool(self.google_client_id)

    # Proxy Secret (Nuxt → FastAPI authentication)
    nuxt_proxy_secret: str = ""
    allow_insecure_proxy_secret: bool = False

    # Optional: Sentry
    sentry_dsn: str = ""

    # Optional: Debug mode (blocked in production)
    debug: bool = False

    @model_validator(mode="after")
    def validate_debug_mode(self) -> "Settings":
        """Prevent debug mode from being enabled in production."""
        if self.debug and self.environment.lower() == "production":
            raise ValueError("Debug mode cannot be enabled in production environment")
        return self

    # Billbee API credentials (formerly per-user, now system-wide in .env)
    billbee_api_key: str = ""
    billbee_username: str = ""
    billbee_password: str = ""

    # Billbee sync label (set on orders after import to prevent re-fetching)
    billbee_sync_label: str = "shop2tax"

    # PayPal API credentials
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_sandbox: bool = False

    # AI Document Extraction (optional, per provider)
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Extraction rate limit (shared tenant, global counter)
    extraction_rate_limit: str = "30/hour"

    # Google Cloud Storage (receipt files, GoBD-WORM)
    gcs_bucket_name: str = ""
    google_cloud_project: str = ""

    # Storage Backend (required: "gcs" | "local")
    storage_backend: str = ""

    # Local Backend (required if storage_backend=local)
    local_storage_path: str = ""

    @model_validator(mode="after")
    def validate_storage_config(self) -> "Settings":
        """Validate storage backend configuration."""
        import os
        import warnings

        if not self.database_url:
            raise ValueError("DATABASE_URL is required.")

        # Backwards-compat: infer gcs from legacy config (D7)
        if not self.storage_backend and self.gcs_bucket_name:
            warnings.warn(
                "STORAGE_BACKEND not set but GCS_BUCKET_NAME found. Inferring STORAGE_BACKEND=gcs. Please set STORAGE_BACKEND explicitly.",
                DeprecationWarning,
                stacklevel=2,
            )
            object.__setattr__(self, "storage_backend", "gcs")

        if not self.storage_backend:
            raise ValueError("STORAGE_BACKEND is required. Set to 'gcs' or 'local'.")

        if self.storage_backend == "gcs":
            if not self.gcs_bucket_name:
                raise ValueError("STORAGE_BACKEND=gcs requires GCS_BUCKET_NAME")
        elif self.storage_backend == "local":
            if not self.local_storage_path:
                raise ValueError("STORAGE_BACKEND=local requires LOCAL_STORAGE_PATH")
            if not os.path.isabs(self.local_storage_path):
                raise ValueError("LOCAL_STORAGE_PATH must be absolute path")
        else:
            raise ValueError(f"Unknown STORAGE_BACKEND: {self.storage_backend}. Use 'gcs' or 'local'.")

        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
