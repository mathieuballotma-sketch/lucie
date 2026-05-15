"""Tests E2E du document_analyzer sur les 5 fixtures fictives."""

from __future__ import annotations

import asyncio

import pytest

from lucie_v1_standalone.document_analyzer import analyze_document
from lucie_v1_standalone.document_analyzer.exceptions import (
    ScannedPDFError,
    UnsupportedFormatError,
)


# ─── Fixtures 1 & 2 : in-scope licenciement (eco + perso) ────────────────────


def test_fixture_1_lic_eco_pdf_in_scope(fixture_lic_eco_pdf):
    result = asyncio.run(analyze_document(str(fixture_lic_eco_pdf)))
    assert result.format == "pdf"
    assert result.pages == 3
    assert result.subject_detected == "droit_social"
    assert result.confidence > 0.5
    assert result.refusal_reason is None
    # Articles applicables retournés (peuvent venir KB curatée ou Légifrance)
    # On exige au moins UN article — la base curatée droit social a L.1233-*
    assert len(result.articles_applicables) >= 1
    # URLs cliquables Légifrance
    for art in result.articles_applicables:
        assert art.url.startswith("https://www.legifrance.gouv.fr/")
        assert 0.0 <= art.relevance <= 1.0


def test_fixture_2_lic_perso_docx_in_scope(fixture_lic_perso_docx):
    result = asyncio.run(analyze_document(str(fixture_lic_perso_docx)))
    assert result.format == "docx"
    assert result.subject_detected == "droit_social"
    assert result.confidence > 0.3
    assert result.refusal_reason is None
    assert len(result.articles_applicables) >= 1


# ─── Fixture 3 : sociétés → out-of-scope ──────────────────────────────────────


def test_fixture_3_societe_sarl_out_of_scope(fixture_societe_sarl_pdf):
    result = asyncio.run(analyze_document(str(fixture_societe_sarl_pdf)))
    assert result.format == "pdf"
    assert result.subject_detected == "societes"
    assert result.articles_applicables == ()
    assert result.refusal_reason is not None
    assert "societes" in result.refusal_reason.lower() or "société" in result.refusal_reason.lower()


# ─── Fixture 4 : pharma → out-of-scope no-theme avec mention Beaume Engine ────


def test_fixture_4_pharma_out_of_scope_with_engine_mention(fixture_pharma_pdf):
    result = asyncio.run(analyze_document(str(fixture_pharma_pdf)))
    assert result.format == "pdf"
    # Pharma n'a aucun thème → subject None
    assert result.subject_detected is None
    assert result.articles_applicables == ()
    assert result.refusal_reason is not None
    # Doit mentionner Beaume Engine ou corpus dédié
    assert (
        "Beaume Engine" in result.refusal_reason
        or "corpus" in result.refusal_reason.lower()
    )


# ─── Fixture 5 : mixte → in-scope + refus partiel sur partie fiscale ──────────


def test_fixture_5_mixte_lic_eco_fiscal_partial(fixture_mixte_docx):
    result = asyncio.run(analyze_document(str(fixture_mixte_docx)))
    assert result.format == "docx"
    assert result.subject_detected == "droit_social"
    assert result.confidence > 0.3
    # Partie lic_eco traitée → articles applicables non vides
    assert len(result.articles_applicables) >= 1
    # Partie fiscale signalée
    assert result.refusal_reason is not None
    assert (
        "fiscal" in result.refusal_reason.lower()
        or "fiscal_comptable" in result.refusal_reason.lower()
    )


# ─── Cas erreurs explicites ──────────────────────────────────────────────────


def test_unsupported_extension_raises(fixture_unsupported):
    with pytest.raises(UnsupportedFormatError):
        asyncio.run(analyze_document(str(fixture_unsupported)))


def test_scan_pdf_raises_scanned_error(fixture_scan_pdf):
    with pytest.raises(ScannedPDFError):
        asyncio.run(analyze_document(str(fixture_scan_pdf)))


# ─── Perf : <30s sur PDF in-scope ─────────────────────────────────────────────


def test_perf_under_30_seconds(fixture_lic_eco_pdf):
    result = asyncio.run(analyze_document(str(fixture_lic_eco_pdf)))
    assert result.processing_time_ms < 30_000, (
        f"processing_time_ms={result.processing_time_ms} > 30 000 — "
        "cible perf <30s ratée"
    )


# ─── Sérialisation to_dict pour démo / wizard W-1 ─────────────────────────────


def test_result_serializable_to_dict(fixture_lic_eco_pdf):
    result = asyncio.run(analyze_document(str(fixture_lic_eco_pdf)))
    payload = result.to_dict()
    assert set(payload.keys()) == {
        "pages",
        "format",
        "subject_detected",
        "confidence",
        "articles_applicables",
        "refusal_reason",
        "processing_time_ms",
    }
    import json

    # Tout doit être JSON-sérialisable
    json.dumps(payload, ensure_ascii=False)
