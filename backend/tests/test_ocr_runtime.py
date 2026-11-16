"""Focused tests for OCR runtime verification and missing-engine fallback.

Verifies:
1. Actual OCR text extraction via Tesseract on raster images (when runtime binary is installed).
2. Explicit detection and fallback behavior when Tesseract binary is missing or offline.
3. Verification that missing Tesseract is NEVER silently treated as successful OCR.
"""
from __future__ import annotations

import io
import pytest
from PIL import Image, ImageDraw

from app.services.document_extraction_service import (
    extract_document_text,
    extract_image_ocr,
)


def create_ocr_test_image(text: str = "INKLOOM BRAND COMPLIANCE") -> bytes:
    """Generate a high-contrast image containing legible rendered text."""
    # Create white canvas 400x120
    img = Image.new("RGB", (400, 120), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Draw dark text with spacing
    draw.text((20, 45), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_missing_tesseract_fails_gracefully_and_is_not_reported_as_success(monkeypatch: pytest.MonkeyPatch):
    """When Tesseract binary is missing or fails, extraction returns empty text

    and explicitly flags the method as 'image-metadata-only (Tesseract engine offline: ...)'
    rather than claiming successful OCR.
    """
    import pytesseract

    def mock_missing_tesseract(*args, **kwargs):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_string", mock_missing_tesseract)

    img_bytes = create_ocr_test_image("INKLOOM BRAND COMPLIANCE")
    result = extract_image_ocr(img_bytes, "png")

    # Verify missing tesseract is NOT silently treated as successful OCR
    assert result.method != "pytesseract-tesseract-ocr"
    assert "image-metadata-only" in result.method
    assert "Tesseract engine offline" in result.method
    assert result.text == ""
    assert result.metadata["width"] == 400
    assert result.metadata["height"] == 120    assert result.metadata["format"] == "PNG"


def test_ocr_runtime_live_extraction():
    """Verify actual OCR text extraction when Tesseract binary is present in the environment.

    In environments with Tesseract installed (such as the updated backend Docker container),
    this test validates real image-to-text conversion.
    """
    import shutil

    tesseract_available = shutil.which("tesseract") is not None
    img_bytes = create_ocr_test_image("INKLOOM BRAND COMPLIANCE")

    if not tesseract_available:
        pytest.skip("Tesseract executable not found on host PATH. Expected in container.")

    result = extract_image_ocr(img_bytes, "png")
    assert result.method == "pytesseract-tesseract-ocr"
    assert "INKLOOM" in result.text.upper() or "COMPLIANCE" in result.text.upper()
    assert result.page_count == 1
    assert result.metadata["width"] == 400
    assert result.metadata["height"] == 120
