"""File storage service for receipt attachments (GoBD-compliant).

Files are stored with content-addressable keys:
  receipts/{YYYY}/{hash}.{ext}

GoBD requirements:
- Storage backend must support WORM in production (files CANNOT be deleted)
- SHA-256 hash verification on every download
- Audit log for all operations (handled by receipt_service.py)
"""

import hashlib
import mimetypes
from datetime import datetime

from app.services.storage_backend import get_storage_backend

# Limits
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Allowed MIME types (security: only safe document types)
ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
    }
)


class FileStorageError(Exception):
    """Raised when file storage operation fails."""


class FileValidationError(FileStorageError):
    """Raised when file validation fails (size, type)."""


class FileIntegrityError(FileStorageError):
    """Raised when file integrity check fails (hash mismatch)."""


def _compute_hash(content: bytes) -> str:
    """Compute SHA-256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def _detect_mime_type(original_name: str, content: bytes) -> str:
    """Detect MIME type from filename and content.

    Uses magic bytes as primary signal, falls back to filename extension.
    """
    # Validate magic bytes for common types
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    # Fall back to extension-based detection
    mime_type, _ = mimetypes.guess_type(original_name)
    return mime_type or "application/octet-stream"


def _get_extension_for_mime(mime_type: str) -> str:
    """Get file extension for MIME type."""
    mapping = {
        "application/pdf": "pdf",
        "image/jpeg": "jpg",
        "image/png": "png",
    }
    return mapping.get(mime_type, "bin")


def store_file(file_content: bytes, original_name: str) -> tuple[str, str, str]:
    """Store file in configured storage backend.

    Args:
        file_content: Raw file bytes
        original_name: Original filename (for MIME detection)

    Returns:
        Tuple of (file_hash, object_name, mime_type)
        object_name format: receipts/{year}/{hash}.{ext}

    Raises:
        FileValidationError: If file exceeds size limit or has invalid type
    """
    # Validate size
    if len(file_content) > MAX_FILE_SIZE:
        raise FileValidationError(f"File exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)} MB")

    # Detect and validate MIME type
    mime_type = _detect_mime_type(original_name, file_content)
    if mime_type not in ALLOWED_MIME_TYPES:
        raise FileValidationError(f"Invalid file type: {mime_type}. Allowed: {', '.join(sorted(ALLOWED_MIME_TYPES))}")

    # Compute content hash
    file_hash = _compute_hash(file_content)

    # Build object name: receipts/{year}/{hash}.{ext}
    year = str(datetime.now().year)
    extension = _get_extension_for_mime(mime_type)
    object_name = f"receipts/{year}/{file_hash}.{extension}"

    # Upload via storage backend (skip if exists — content-addressable)
    backend = get_storage_backend()
    backend.upload(object_name, file_content, mime_type)

    return (file_hash, object_name, mime_type)


def get_file_content(object_name: str, expected_hash: str) -> bytes:
    """Download file from storage backend with integrity verification.

    Args:
        object_name: Storage object name
        expected_hash: Expected SHA-256 hash (hex)

    Returns:
        File content bytes

    Raises:
        FileIntegrityError: If hash doesn't match (file corrupted/tampered)
    """
    backend = get_storage_backend()
    content = backend.download(object_name)
    actual_hash = _compute_hash(content)

    if actual_hash != expected_hash:
        raise FileIntegrityError(f"File integrity check failed: expected {expected_hash[:16]}..., got {actual_hash[:16]}...")

    return content


def verify_file(object_name: str, expected_hash: str) -> bool:
    """Verify file integrity without returning content.

    Args:
        object_name: Storage object name
        expected_hash: Expected SHA-256 hash (hex)

    Returns:
        True if file exists and hash matches, False otherwise
    """
    backend = get_storage_backend()
    if not backend.exists(object_name):
        return False

    content = backend.download(object_name)
    actual_hash = _compute_hash(content)
    return actual_hash == expected_hash
