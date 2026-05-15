"""Tests unitaires du détecteur de sujet juridique."""

from __future__ import annotations

from lucie_v1_standalone.document_analyzer.subject_detector import (
    _confidence_from_hits,
    detect_subject,
)


def test_detect_subject_droit_social():
    text = (
        "Licenciement économique de M. Dupont, salarié protégé. "
        "Convention collective applicable. CSP proposé. Préavis 3 mois. "
        "PSE en cours. Critères d'ordre des licenciements appliqués."
    )
    theme, confidence, scored = detect_subject(text)
    assert theme == "droit_social"
    assert confidence > 0.5
    assert scored[0][0] == "droit_social"


def test_detect_subject_societes():
    text = (
        "Cession de parts SARL. Capital social 50 000 EUR. Gérant nommé "
        "par assemblée générale. Statuts modifiés. SAS et SA non concernées."
    )
    theme, confidence, _scored = detect_subject(text)
    assert theme == "societes"
    assert confidence > 0.0


def test_detect_subject_empty_returns_none():
    theme, confidence, scored = detect_subject("")
    assert theme is None
    assert confidence == 0.0
    assert scored == []


def test_detect_subject_whitespace_returns_none():
    theme, _conf, _scored = detect_subject("    \n  \t ")
    assert theme is None


def test_detect_subject_unknown_domain_returns_none():
    text = "Publicité médicament paracétamol. ANSM. Visa PM. Pharmacovigilance."
    theme, _conf, _scored = detect_subject(text)
    # Aucun thème ne couvre pharma → None attendu
    assert theme is None


def test_confidence_bounded():
    # 100 hits doit saturer à 1.0, jamais > 1.0
    assert _confidence_from_hits(100, 1000) == 1.0
    # 0 hit → 0.0
    assert _confidence_from_hits(0, 1000) == 0.0
    # Doc très court pénalisé
    short = _confidence_from_hits(3, 20)
    normal = _confidence_from_hits(3, 200)
    assert short < normal
