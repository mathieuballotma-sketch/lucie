"""Tests unitaires du parser PDF déterministe."""

from __future__ import annotations

import pytest

from lucie_v1_standalone.document_analyzer.exceptions import (
    CorruptedFileError,
    EmptyDocumentError,
    ScannedPDFError,
)
from lucie_v1_standalone.document_analyzer.pdf_parser import parse_pdf


def test_parse_pdf_extracts_text_and_page_count(fixture_lic_eco_pdf):
    text, pages = parse_pdf(fixture_lic_eco_pdf)
    assert pages == 3
    assert "Dupont" in text
    assert "licenciement économique" in text.lower()
    assert "CSP" in text or "sécurisation professionnelle" in text


def test_parse_pdf_returns_combined_pages_text(fixture_lic_eco_pdf):
    text, _pages = parse_pdf(fixture_lic_eco_pdf)
    # Mots provenant de pages distinctes (1, 2, 3)
    assert "Société X" in text or "Société" in text
    assert "Pièces communiquées" in text
    assert "prud'hommes" in text.lower()


def test_parse_pdf_empty_raises(fixture_empty_pdf):
    with pytest.raises(EmptyDocumentError):
        parse_pdf(fixture_empty_pdf)


def test_parse_pdf_scan_image_raises(fixture_scan_pdf):
    with pytest.raises(ScannedPDFError) as exc_info:
        parse_pdf(fixture_scan_pdf)
    assert "OCR" in str(exc_info.value)


def test_parse_pdf_corrupt_raises(fixture_corrupt_pdf):
    with pytest.raises(CorruptedFileError):
        parse_pdf(fixture_corrupt_pdf)


def test_parse_pdf_missing_file_raises(tmp_path):
    with pytest.raises(CorruptedFileError):
        parse_pdf(tmp_path / "does_not_exist.pdf")
