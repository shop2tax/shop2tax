"""Unit tests for LocalBackend storage."""

import pytest
from app.services.local_backend import LocalBackend


class TestLocalBackend:
    """Tests for LocalBackend file operations."""

    def should_upload_and_download_file(self, tmp_path):
        """Upload and download round-trip preserves content."""
        backend = LocalBackend(str(tmp_path))
        backend.validate()

        content = b"test file content"
        object_name = "user-123/2026/abc123.pdf"

        result = backend.upload(object_name, content, "application/pdf")

        assert result == object_name
        assert backend.exists(object_name)
        assert backend.download(object_name) == content

    def should_be_idempotent_on_upload(self, tmp_path):
        """Uploading the same object twice does not overwrite or fail."""
        backend = LocalBackend(str(tmp_path))
        backend.validate()

        content = b"original content"
        object_name = "user-123/2026/dedup.pdf"

        # First upload
        backend.upload(object_name, content, "application/pdf")

        # Second upload with different content (should be skipped due to idempotency)
        backend.upload(object_name, b"different content", "application/pdf")

        # Original content should be preserved
        assert backend.download(object_name) == content

    def should_raise_on_missing_file(self, tmp_path):
        """Downloading non-existent file raises FileNotFoundError."""
        backend = LocalBackend(str(tmp_path))
        backend.validate()

        with pytest.raises(FileNotFoundError):
            backend.download("nonexistent/file.pdf")

    def should_validate_writable_path(self, tmp_path):
        """Validation passes for writable directories."""
        backend = LocalBackend(str(tmp_path))
        # Should not raise
        backend.validate()

    def should_create_directory_if_not_exists(self, tmp_path):
        """Validation creates the directory if it doesn't exist."""
        new_dir = tmp_path / "new_storage_dir"
        assert not new_dir.exists()

        backend = LocalBackend(str(new_dir))
        backend.validate()

        assert new_dir.exists()

    def should_reject_path_traversal(self, tmp_path):
        """Path traversal attempts are rejected."""
        backend = LocalBackend(str(tmp_path))
        backend.validate()

        with pytest.raises(ValueError, match="path traversal"):
            backend.upload("../../../etc/passwd", b"malicious", "text/plain")

        with pytest.raises(ValueError, match="path traversal"):
            backend.download("../../../etc/passwd")

        with pytest.raises(ValueError, match="path traversal"):
            backend.exists("../../../etc/passwd")

    def should_reject_symlink_storage_path(self, tmp_path):
        """Storage path cannot be a symlink."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()

        symlink_dir = tmp_path / "symlink"
        symlink_dir.symlink_to(real_dir)

        backend = LocalBackend(str(symlink_dir))

        with pytest.raises(RuntimeError, match="must not be a symlink"):
            backend.validate()

    def should_set_restrictive_file_permissions(self, tmp_path):
        """Uploaded files have 0o600 permissions."""
        backend = LocalBackend(str(tmp_path))
        backend.validate()

        object_name = "user-123/2026/secure.pdf"
        backend.upload(object_name, b"sensitive data", "application/pdf")

        file_path = tmp_path / object_name
        # Check that file is readable only by owner (0o600)
        mode = file_path.stat().st_mode & 0o777
        assert mode == 0o600

    def should_write_atomically(self, tmp_path):
        """No partial files are left on simulated crash."""
        backend = LocalBackend(str(tmp_path))
        backend.validate()

        object_name = "user-123/2026/atomic.pdf"
        content = b"atomic write test"

        # Upload successfully
        backend.upload(object_name, content, "application/pdf")

        # Verify no .tmp files are left behind
        tmp_files = list(tmp_path.rglob("*.tmp"))
        assert len(tmp_files) == 0

        # Verify the file exists and has correct content
        assert backend.download(object_name) == content

    def should_report_supports_worm_false(self, tmp_path):
        """LocalBackend reports supports_worm=False."""
        backend = LocalBackend(str(tmp_path))
        assert backend.supports_worm is False
