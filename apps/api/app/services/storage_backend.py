"""Pluggable storage backend for receipt files.

Provides a Protocol for storage backends and a factory function to get the configured backend.
Community can implement additional backends (S3, Azure, etc.) by following the Protocol.
"""

from functools import lru_cache
from typing import Protocol


class StorageBackend(Protocol):
    """Pluggable storage backend for receipt files.

    Note: delete() is intentionally omitted — GoBD WORM compliance
    requires files to be immutable once stored.

    object_name format is caller-determined (e.g. "receipts/{year}/{hash}.{ext}").
    content_type is a hint — backends MAY store it (GCS does) but are not required to.
    """

    @property
    def supports_worm(self) -> bool:
        """True if backend enforces WORM (Write-Once-Read-Many).

        Backends returning False are blocked in production (see lifespan).
        """
        ...

    def validate(self) -> None:
        """Validate backend configuration on startup.

        Raises RuntimeError with actionable message if invalid.
        Use logging.getLogger(__name__) for status output, not print().
        """
        ...

    def upload(self, object_name: str, content: bytes, content_type: str) -> str:
        """Upload content. Returns object_name. Idempotent (skips if exists)."""
        ...

    def download(self, object_name: str) -> bytes:
        """Download content. Raises FileNotFoundError if missing."""
        ...

    def exists(self, object_name: str) -> bool:
        """Check if object exists."""
        ...


@lru_cache
def get_storage_backend() -> StorageBackend:
    """Get configured storage backend. Cached singleton."""
    from app.config import get_settings

    settings = get_settings()

    if settings.storage_backend == "gcs":
        from app.services.gcs_backend import GCSBackend

        return GCSBackend(settings.gcs_bucket_name, settings.google_cloud_project)
    elif settings.storage_backend == "local":
        from app.services.local_backend import LocalBackend

        return LocalBackend(settings.local_storage_path)

    raise RuntimeError(f"Unknown storage backend: {settings.storage_backend}")
