"""Local filesystem backend for receipt file storage (development only).

WARNING: This backend does NOT provide WORM (Write-Once-Read-Many) protection.
It is blocked in production environments. Use GCS for production deployments.
"""

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalBackend:
    """Local filesystem backend for development/testing."""

    def __init__(self, storage_path: str) -> None:
        """Initialize with base storage path."""
        self._base_path = Path(storage_path)

    @property
    def supports_worm(self) -> bool:
        """Local filesystem does not support WORM."""
        return False

    def validate(self) -> None:
        """Validate local storage path exists, is writable, and not a symlink."""
        # Security: reject symlinks (could point outside intended directory)
        if self._base_path.is_symlink():
            raise RuntimeError(f"LOCAL_STORAGE_PATH must not be a symlink: {self._base_path}")

        if not self._base_path.exists():
            self._base_path.mkdir(parents=True, exist_ok=True)

        # Test write permission with tempfile (no race condition)
        try:
            with tempfile.NamedTemporaryFile(dir=self._base_path, delete=True):
                pass
        except OSError as error:
            raise RuntimeError(f"LOCAL_STORAGE_PATH '{self._base_path}' is not writable: {error}")

        logger.warning(
            "Storage: local (NO WORM protection — not GoBD compliant). Path: %s",
            self._base_path,
        )

    def _resolve_safe_path(self, object_name: str) -> Path:
        """Resolve path and validate it stays within base directory."""
        resolved = (self._base_path / object_name).resolve()
        if not resolved.is_relative_to(self._base_path.resolve()):
            raise ValueError(f"Invalid object name (path traversal): {object_name}")
        return resolved

    def upload(self, object_name: str, content: bytes, content_type: str) -> str:
        """Upload content to local filesystem.

        Skips upload if file already exists (content-addressable = idempotent).
        Uses atomic write (temp file + rename) to prevent partial files.
        """
        file_path = self._resolve_safe_path(object_name)
        if file_path.exists():
            return object_name

        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file → rename (prevents partial files on crash)
        with tempfile.NamedTemporaryFile(dir=file_path.parent, delete=False, suffix=".tmp") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        tmp_path.chmod(0o600)  # Restrict permissions (tax/accounting files)
        tmp_path.rename(file_path)
        return object_name

    def download(self, object_name: str) -> bytes:
        """Download content from local filesystem."""
        file_path = self._resolve_safe_path(object_name)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {object_name}")
        return file_path.read_bytes()

    def exists(self, object_name: str) -> bool:
        """Check if file exists."""
        file_path = self._resolve_safe_path(object_name)
        return file_path.exists()
