"""Unit tests for storage backend configuration validation."""

import warnings

import pytest
from app.config import Settings
from pydantic import ValidationError


class TestStorageConfig:
    """Tests for storage backend configuration validation."""

    def should_reject_missing_storage_backend(self, monkeypatch):
        """STORAGE_BACKEND is required when GCS_BUCKET_NAME is not set."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        monkeypatch.delenv("GCS_BUCKET_NAME", raising=False)

        with pytest.raises(ValidationError, match="STORAGE_BACKEND is required"):
            Settings()

    def should_reject_relative_local_path(self, monkeypatch):
        """LOCAL_STORAGE_PATH must be absolute."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        monkeypatch.setenv("LOCAL_STORAGE_PATH", "relative/path")

        with pytest.raises(ValidationError, match="must be absolute path"):
            Settings()

    def should_reject_gcs_without_bucket_name(self, monkeypatch):
        """STORAGE_BACKEND=gcs requires GCS_BUCKET_NAME."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "gcs")
        monkeypatch.delenv("GCS_BUCKET_NAME", raising=False)

        with pytest.raises(ValidationError, match="requires GCS_BUCKET_NAME"):
            Settings()

    def should_reject_local_without_storage_path(self, monkeypatch):
        """STORAGE_BACKEND=local requires LOCAL_STORAGE_PATH."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        monkeypatch.delenv("LOCAL_STORAGE_PATH", raising=False)

        with pytest.raises(ValidationError, match="requires LOCAL_STORAGE_PATH"):
            Settings()

    def should_reject_unknown_storage_backend(self, monkeypatch):
        """Unknown STORAGE_BACKEND values are rejected."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "s3")

        with pytest.raises(ValidationError, match="Unknown STORAGE_BACKEND"):
            Settings()

    def should_accept_valid_gcs_config(self, monkeypatch):
        """Valid GCS configuration passes validation."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "gcs")
        monkeypatch.setenv("GCS_BUCKET_NAME", "my-bucket")

        settings = Settings()
        assert settings.storage_backend == "gcs"
        assert settings.gcs_bucket_name == "my-bucket"

    def should_accept_valid_local_config(self, monkeypatch):
        """Valid local configuration passes validation."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        monkeypatch.setenv("LOCAL_STORAGE_PATH", "/data/receipts")

        settings = Settings()
        assert settings.storage_backend == "local"
        assert settings.local_storage_path == "/data/receipts"

    def should_infer_gcs_from_legacy_config(self, monkeypatch):
        """When STORAGE_BACKEND is empty but GCS_BUCKET_NAME is set, infer gcs."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        monkeypatch.setenv("GCS_BUCKET_NAME", "legacy-bucket")

        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            settings = Settings()

        assert settings.storage_backend == "gcs"
        assert settings.gcs_bucket_name == "legacy-bucket"

        # Verify deprecation warning was emitted
        deprecation_warnings = [w for w in caught_warnings if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        assert "STORAGE_BACKEND not set but GCS_BUCKET_NAME found" in str(deprecation_warnings[0].message)

    def should_emit_deprecation_warning_on_infer(self, monkeypatch):
        """Deprecation warning includes instruction to set STORAGE_BACKEND explicitly."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        monkeypatch.setenv("GCS_BUCKET_NAME", "legacy-bucket")

        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            Settings()

        deprecation_warnings = [w for w in caught_warnings if issubclass(w.category, DeprecationWarning)]
        assert any("Please set STORAGE_BACKEND explicitly" in str(w.message) for w in deprecation_warnings)
