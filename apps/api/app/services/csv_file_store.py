"""In-memory CSV file store with TTL.

Stores uploaded CSV files temporarily (30 minutes) so that follow-up
operations (analyze, parse, enrich) can reference them by file_id
instead of re-uploading the file each time.
"""

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

FILE_TTL = timedelta(minutes=30)


@dataclass(slots=True)
class StoredFile:
    """A temporarily stored CSV file."""

    file_id: str
    filename: str
    content: bytes
    expires_at: datetime


# Global file store (tenant-wide, shared across requests)
_file_store: dict[str, StoredFile] = {}
_lock = threading.Lock()


def store_csv_file(filename: str, content: bytes) -> StoredFile:
    """Store CSV file content and return a StoredFile with file_id.

    Args:
        filename: Original filename
        content: Raw CSV bytes

    Returns:
        StoredFile with generated file_id and expiration
    """
    cleanup_expired()

    file_id = str(uuid4())
    stored = StoredFile(
        file_id=file_id,
        filename=filename,
        content=content,
        expires_at=datetime.now(UTC) + FILE_TTL,
    )

    with _lock:
        _file_store[file_id] = stored

    return stored


def get_csv_file(file_id: str) -> StoredFile | None:
    """Retrieve a stored CSV file by ID.

    Returns None if file_id not found or expired.
    """
    with _lock:
        stored = _file_store.get(file_id)

    if stored is None:
        return None

    if stored.expires_at < datetime.now(UTC):
        with _lock:
            _file_store.pop(file_id, None)
        return None

    return stored


def cleanup_expired() -> int:
    """Remove expired files. Returns number of files removed."""
    now = datetime.now(UTC)
    removed = 0

    with _lock:
        expired_ids = [fid for fid, stored in _file_store.items() if stored.expires_at < now]
        for file_id in expired_ids:
            del _file_store[file_id]
            removed += 1

    return removed
