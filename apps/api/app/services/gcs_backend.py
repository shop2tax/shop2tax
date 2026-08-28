"""Google Cloud Storage backend for receipt file storage (GoBD-WORM)."""

import logging
import warnings

from google.cloud import storage

logger = logging.getLogger(__name__)


def _create_storage_client(project: str) -> storage.Client:
    """Create GCS client with quota project to suppress ADC warnings."""
    import google.auth

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        credentials, _ = google.auth.default()

    if project and hasattr(credentials, "with_quota_project"):
        credentials = credentials.with_quota_project(project)

    return storage.Client(project=project or None, credentials=credentials)


class GCSBackend:
    """Google Cloud Storage backend with WORM support."""

    def __init__(self, bucket_name: str, project: str = "") -> None:
        """Initialize with ADC and cache bucket reference."""
        self._client = _create_storage_client(project)
        self._bucket = self._client.bucket(bucket_name)
        self._bucket_name = bucket_name

    @property
    def supports_worm(self) -> bool:
        """GCS with retention policy supports WORM."""
        return True

    def validate(self) -> None:
        """Validate GCS: auth, EU region, retention policy."""
        from google.api_core.exceptions import GoogleAPIError
        from google.auth.exceptions import RefreshError

        try:
            bucket = self._client.get_bucket(self._bucket_name, timeout=10)
        except RefreshError:
            raise RuntimeError("GCS authentication expired. Run: gcloud auth application-default login")
        except GoogleAPIError as error:
            raise RuntimeError(f"GCS connection failed: {error}")

        # DSGVO: EU region
        location = bucket.location.lower()
        if not location.startswith("europe"):
            raise RuntimeError(f"GCS bucket '{self._bucket_name}' is in '{location}', expected 'europe-*' (DSGVO requirement)")

        # GoBD: Retention policy
        if not bucket.retention_period:
            raise RuntimeError(f"GCS bucket '{self._bucket_name}' has no retention policy. GoBD requires 10-year retention (3653 days).")

        retention_days = bucket.retention_period // 86400
        logger.info(
            "Storage: gcs (WORM enabled, %s, retention=%d days)",
            bucket.location,
            retention_days,
        )

    def upload(self, object_name: str, content: bytes, content_type: str) -> str:
        """Upload bytes to GCS. Returns object name.

        Skips upload if blob already exists (content-addressable = idempotent).
        """
        blob = self._bucket.blob(object_name)
        if blob.exists():
            return object_name
        blob.upload_from_string(content, content_type=content_type)
        return object_name

    def download(self, object_name: str) -> bytes:
        """Download blob content. Raises FileNotFoundError if missing."""
        from google.api_core.exceptions import NotFound

        blob = self._bucket.blob(object_name)
        try:
            return blob.download_as_bytes()
        except NotFound:
            raise FileNotFoundError(f"File not found in GCS: {object_name}")

    def exists(self, object_name: str) -> bool:
        """Check if blob exists."""
        return self._bucket.blob(object_name).exists()
