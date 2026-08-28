"""Unit tests for GCS storage functions (receipt_storage module)."""

import hashlib

from app.services.receipt_storage import _compute_hash, _detect_mime_type, _get_extension_for_mime

# --- SHA-256 hash computation ---


def should_compute_sha256_hash():
    content = b"hello world"
    expected = hashlib.sha256(content).hexdigest()
    assert _compute_hash(content) == expected


def should_compute_different_hashes_for_different_content():
    assert _compute_hash(b"file-a") != _compute_hash(b"file-b")


def should_compute_consistent_hash_for_same_content():
    content = b"deterministic content"
    assert _compute_hash(content) == _compute_hash(content)


# --- MIME type detection from magic bytes ---


def should_detect_pdf_from_magic_bytes():
    pdf_content = b"%PDF-1.4 fake pdf content"
    assert _detect_mime_type("unknown.bin", pdf_content) == "application/pdf"


def should_detect_jpeg_from_magic_bytes():
    jpeg_content = b"\xff\xd8\xff\xe0 fake jpeg"
    assert _detect_mime_type("unknown.bin", jpeg_content) == "image/jpeg"


def should_detect_png_from_magic_bytes():
    png_content = b"\x89PNG\r\n\x1a\n fake png"
    assert _detect_mime_type("unknown.bin", png_content) == "image/png"


def should_fallback_to_extension_when_no_magic_match():
    content = b"some random bytes"
    assert _detect_mime_type("document.pdf", content) == "application/pdf"


def should_return_octet_stream_for_unknown():
    content = b"some random bytes"
    assert _detect_mime_type("noextension", content) == "application/octet-stream"


# --- Extension for MIME type ---


def should_map_pdf_mime_to_pdf_extension():
    assert _get_extension_for_mime("application/pdf") == "pdf"


def should_map_jpeg_mime_to_jpg_extension():
    assert _get_extension_for_mime("image/jpeg") == "jpg"


def should_map_png_mime_to_png_extension():
    assert _get_extension_for_mime("image/png") == "png"


def should_fallback_to_bin_for_unknown_mime():
    assert _get_extension_for_mime("application/octet-stream") == "bin"


# --- Object name building ---


def should_build_correct_object_name():
    """Verify store_file produces receipts/{year}/{hash}.{ext} format."""
    from datetime import datetime
    from unittest.mock import MagicMock, patch

    pdf_content = b"%PDF-1.4 test content"
    expected_hash = hashlib.sha256(pdf_content).hexdigest()
    year = str(datetime.now().year)

    fake_backend = MagicMock()
    fake_backend.upload.return_value = f"receipts/{year}/{expected_hash}.pdf"

    with patch("app.services.receipt_storage.get_storage_backend", return_value=fake_backend):
        from app.services.receipt_storage import store_file

        file_hash, object_name, mime_type = store_file(pdf_content, "invoice.pdf")

    assert file_hash == expected_hash
    assert object_name == f"receipts/{year}/{expected_hash}.pdf"
    assert mime_type == "application/pdf"
    fake_backend.upload.assert_called_once_with(
        f"receipts/{year}/{expected_hash}.pdf",
        pdf_content,
        "application/pdf",
    )
