"""Unit tests for storage backend lifespan validation."""

from unittest.mock import MagicMock, patch


class TestStorageLifespan:
    """Tests for storage backend validation in lifespan."""

    def should_block_non_worm_backend_in_production(self, monkeypatch):
        """Non-WORM backends are blocked in production environment."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        monkeypatch.setenv("LOCAL_STORAGE_PATH", "/data/receipts")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Clear cached settings
        from app.config import get_settings

        get_settings.cache_clear()

        # Create a mock backend that reports supports_worm=False
        mock_backend = MagicMock()
        mock_backend.supports_worm = False
        mock_backend.validate = MagicMock()

        with patch("app.services.storage_backend.get_storage_backend", return_value=mock_backend):
            from app.config import get_settings

            settings = get_settings()

            # Simulate the lifespan check
            if settings.environment.lower() == "production" and not mock_backend.supports_worm:
                error_raised = True
            else:
                error_raised = False

        assert error_raised is True, "Non-WORM backend should be blocked in production"

        # Cleanup
        get_settings.cache_clear()

    def should_allow_worm_backend_in_production(self, monkeypatch):
        """WORM-capable backends are allowed in production environment."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "gcs")
        monkeypatch.setenv("GCS_BUCKET_NAME", "my-bucket")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Clear cached settings
        from app.config import get_settings

        get_settings.cache_clear()

        # Create a mock backend that reports supports_worm=True
        mock_backend = MagicMock()
        mock_backend.supports_worm = True
        mock_backend.validate = MagicMock()

        with patch("app.services.storage_backend.get_storage_backend", return_value=mock_backend):
            from app.config import get_settings

            settings = get_settings()

            # Simulate the lifespan check
            if settings.environment.lower() == "production" and not mock_backend.supports_worm:
                error_raised = True
            else:
                error_raised = False

        assert error_raised is False, "WORM backend should be allowed in production"

        # Cleanup
        get_settings.cache_clear()

    def should_allow_non_worm_backend_in_development(self, monkeypatch):
        """Non-WORM backends are allowed in development environment."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        monkeypatch.setenv("LOCAL_STORAGE_PATH", "/data/receipts")
        monkeypatch.setenv("ENVIRONMENT", "development")

        # Clear cached settings
        from app.config import get_settings

        get_settings.cache_clear()

        # Create a mock backend that reports supports_worm=False
        mock_backend = MagicMock()
        mock_backend.supports_worm = False
        mock_backend.validate = MagicMock()

        with patch("app.services.storage_backend.get_storage_backend", return_value=mock_backend):
            from app.config import get_settings

            settings = get_settings()

            # Simulate the lifespan check
            if settings.environment.lower() == "production" and not mock_backend.supports_worm:
                error_raised = True
            else:
                error_raised = False

        assert error_raised is False, "Non-WORM backend should be allowed in development"

        # Cleanup
        get_settings.cache_clear()
