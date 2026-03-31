"""
Tests unitaires pour AccountingAgent.

Couverture :
  - Extraction JSON (parse_invoice_json)
  - Normalisation des données (normalize_invoice_data)
  - Sanitization des noms (sanitize_name)
  - Construction de noms de fichiers (build_filename)
  - Construction de l'arborescence (build_output_path)
  - Détection des colonnes CSV (detect_csv_columns)
  - Parsing des montants et dates bancaires
  - Réconciliation bancaire (match, orphelin, tolérance)
  - Traitement batch complet (5 factures mock)
  - can_handle
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.agents.accounting_agent import (
    AccountingAgent,
    InvoiceData,
    _VALID_CATEGORIES,
)


# ── Fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def agent() -> AccountingAgent:
    llm = MagicMock()
    bus = MagicMock()
    return AccountingAgent(llm, bus, {})


def _make_invoice(
    vendor: str = "EDF",
    date: str = "2026-03-15",
    amount_ttc: float = 142.50,
    vat_amount: float = 23.75,
    category: str = "Energie",
    source_path: str = "/tmp/facture.pdf",
) -> InvoiceData:
    return InvoiceData(
        vendor=vendor,
        date=date,
        amount_ttc=amount_ttc,
        vat_amount=vat_amount,
        category=category,
        source_path=source_path,
    )


# ── can_handle ─────────────────────────────────────────────────────────────────


def test_can_handle_facture(agent: AccountingAgent) -> None:
    assert agent.can_handle("traite mes factures pdf") is True


def test_can_handle_compta(agent: AccountingAgent) -> None:
    assert agent.can_handle("aide moi pour la comptabilité") is True


def test_can_handle_invoice(agent: AccountingAgent) -> None:
    assert agent.can_handle("process my invoices") is True


def test_can_handle_tva(agent: AccountingAgent) -> None:
    assert agent.can_handle("extrait la TVA de ce document") is True


def test_can_handle_no_match(agent: AccountingAgent) -> None:
    assert agent.can_handle("quelle heure est-il ?") is False


def test_can_handle_empty(agent: AccountingAgent) -> None:
    assert agent.can_handle("") is False


# ── _parse_invoice_json ────────────────────────────────────────────────────────


def test_parse_json_valid(agent: AccountingAgent) -> None:
    raw = '{"vendor": "EDF", "date": "2026-03-15", "amount_ttc": 142.50, "vat_amount": 23.75, "category": "Energie"}'
    result = AccountingAgent._parse_invoice_json(raw)
    assert result is not None
    assert result["vendor"] == "EDF"
    assert result["amount_ttc"] == 142.50


def test_parse_json_with_markdown_fence(agent: AccountingAgent) -> None:
    raw = '```json\n{"vendor": "SNCF", "date": "2026-01-10", "amount_ttc": 45.0, "vat_amount": 7.5, "category": "Transport"}\n```'
    result = AccountingAgent._parse_invoice_json(raw)
    assert result is not None
    assert result["vendor"] == "SNCF"


def test_parse_json_with_surrounding_text(agent: AccountingAgent) -> None:
    raw = 'Voici le résultat : {"vendor": "Free", "date": "2026-02-01", "amount_ttc": 29.99, "vat_amount": 5.0, "category": "Telecom"} merci'
    result = AccountingAgent._parse_invoice_json(raw)
    assert result is not None
    assert result["vendor"] == "Free"


def test_parse_json_invalid_returns_none(agent: AccountingAgent) -> None:
    result = AccountingAgent._parse_invoice_json("aucun JSON ici")
    assert result is None


def test_parse_json_empty_returns_none(agent: AccountingAgent) -> None:
    result = AccountingAgent._parse_invoice_json("")
    assert result is None


def test_parse_json_qwen_prefix_style(agent: AccountingAgent) -> None:
    """Simule la sortie typique de Qwen : 'Voici le JSON :' avant le bloc."""
    raw = 'Voici le JSON :\n{"vendor": "SFR", "date": "2026-03-20", "amount_ttc": 19.99, "vat_amount": 3.33, "category": "Telecom"}'
    result = AccountingAgent._parse_invoice_json(raw)
    assert result is not None
    assert result["vendor"] == "SFR"


def test_parse_json_extra_text_after_block(agent: AccountingAgent) -> None:
    """LLM ajoute du texte après le JSON."""
    raw = '{"vendor": "IKEA", "date": "2026-03-25", "amount_ttc": 250.00, "vat_amount": 41.67, "category": "Fournitures"}\n\nJ\'espère que cela correspond.'
    result = AccountingAgent._parse_invoice_json(raw)
    assert result is not None
    assert result["vendor"] == "IKEA"


# ── _normalize_invoice_data ────────────────────────────────────────────────────


def test_normalize_valid_data(agent: AccountingAgent) -> None:
    raw: Dict[str, Any] = {
        "vendor": "Orange",
        "date": "2026-03-01",
        "amount_ttc": 59.99,
        "vat_amount": 10.0,
        "category": "Telecom",
    }
    inv = AccountingAgent._normalize_invoice_data(raw, "/tmp/orange.pdf")
    assert inv.vendor == "Orange"
    assert inv.date == "2026-03-01"
    assert inv.amount_ttc == pytest.approx(59.99)
    assert inv.category == "Telecom"


def test_normalize_null_vendor_string(agent: AccountingAgent) -> None:
    raw: Dict[str, Any] = {"vendor": "null", "date": "2026-03-01", "amount_ttc": 10.0, "vat_amount": None, "category": "Autre"}
    inv = AccountingAgent._normalize_invoice_data(raw, "/tmp/x.pdf")
    assert inv.vendor is None


def test_normalize_invalid_category_defaults_to_autre(agent: AccountingAgent) -> None:
    raw: Dict[str, Any] = {"vendor": "Acme", "date": "2026-03-01", "amount_ttc": 50.0, "vat_amount": None, "category": "InvalideCat"}
    inv = AccountingAgent._normalize_invoice_data(raw, "/tmp/x.pdf")
    assert inv.category == "Autre"


def test_normalize_bad_date_format_becomes_none(agent: AccountingAgent) -> None:
    raw: Dict[str, Any] = {"vendor": "X", "date": "15/03/2026", "amount_ttc": 10.0, "vat_amount": None, "category": "Autre"}
    inv = AccountingAgent._normalize_invoice_data(raw, "/tmp/x.pdf")
    assert inv.date is None


def test_normalize_amount_as_string(agent: AccountingAgent) -> None:
    raw: Dict[str, Any] = {"vendor": "X", "date": "2026-03-01", "amount_ttc": "142.50", "vat_amount": None, "category": "Autre"}
    inv = AccountingAgent._normalize_invoice_data(raw, "/tmp/x.pdf")
    assert inv.amount_ttc == pytest.approx(142.50)


# ── _sanitize_name ─────────────────────────────────────────────────────────────


def test_sanitize_removes_special_chars() -> None:
    result = AccountingAgent._sanitize_name("EDF/GDF@2026!")
    assert "/" not in result
    assert "@" not in result
    assert "!" not in result


def test_sanitize_replaces_spaces_with_underscore() -> None:
    result = AccountingAgent._sanitize_name("Orange France Telecom")
    assert " " not in result
    assert "_" in result


def test_sanitize_handles_accents() -> None:
    result = AccountingAgent._sanitize_name("Électricité de France")
    assert "é" not in result
    assert "è" not in result


def test_sanitize_empty_string_returns_inconnu() -> None:
    result = AccountingAgent._sanitize_name("")
    assert result == "Inconnu"


def test_sanitize_whitespace_only_returns_inconnu() -> None:
    result = AccountingAgent._sanitize_name("   ")
    assert result == "Inconnu"


def test_sanitize_truncates_long_names() -> None:
    long_name = "A" * 100
    result = AccountingAgent._sanitize_name(long_name)
    assert len(result) <= 50


# ── _build_filename ────────────────────────────────────────────────────────────


def test_build_filename_complete() -> None:
    inv = _make_invoice(vendor="EDF", date="2026-03-15", amount_ttc=142.50)
    filename = AccountingAgent._build_filename(inv, ".pdf")
    assert filename == "2026-03-15_EDF_142.50.pdf"


def test_build_filename_missing_vendor() -> None:
    inv = _make_invoice(vendor=None, date="2026-03-15", amount_ttc=50.0)  # type: ignore[arg-type]
    filename = AccountingAgent._build_filename(inv, ".pdf")
    assert "Inconnu" in filename
    assert "2026-03-15" in filename


def test_build_filename_missing_date() -> None:
    inv = _make_invoice(date=None, amount_ttc=50.0)  # type: ignore[arg-type]
    filename = AccountingAgent._build_filename(inv, ".pdf")
    assert "0000-00-00" in filename


def test_build_filename_missing_amount() -> None:
    inv = _make_invoice(amount_ttc=None)  # type: ignore[arg-type]
    filename = AccountingAgent._build_filename(inv, ".pdf")
    assert "0.00" in filename


def test_build_filename_strips_dot_from_extension() -> None:
    inv = _make_invoice()
    filename = AccountingAgent._build_filename(inv, ".pdf")
    assert filename.endswith(".pdf")
    # Pas de double point
    assert ".." not in filename


# ── _build_output_path ─────────────────────────────────────────────────────────


def test_build_output_path_structure(tmp_path: Path) -> None:
    inv = _make_invoice(date="2026-03-15", category="Energie")
    result = AccountingAgent._build_output_path(tmp_path, inv, "2026-03-15_EDF_142.50.pdf")
    assert "Compta" in result.parts
    assert "2026" in result.parts
    assert "Energie" in result.parts


def test_build_output_path_unknown_date(tmp_path: Path) -> None:
    inv = _make_invoice(date=None)  # type: ignore[arg-type]
    result = AccountingAgent._build_output_path(tmp_path, inv, "0000-00-00_Inconnu_0.00.pdf")
    assert "0000" in result.parts


def test_build_output_path_creates_correct_depth(tmp_path: Path) -> None:
    inv = _make_invoice(date="2026-05-10", category="Transport")
    result = AccountingAgent._build_output_path(tmp_path, inv, "test.pdf")
    # tmp_path / Compta / 2026 / Transport / test.pdf
    assert result.parent.name == "Transport"
    assert result.parent.parent.name == "2026"
    assert result.parent.parent.parent.name == "Compta"


# ── _detect_csv_columns ────────────────────────────────────────────────────────


def test_detect_csv_columns_standard() -> None:
    headers = ["date", "montant", "libelle"]
    date_idx, amount_idx, label_idx = AccountingAgent._detect_csv_columns(headers)
    assert date_idx == 0
    assert amount_idx == 1
    assert label_idx == 2


def test_detect_csv_columns_french_accents() -> None:
    headers = ["Date valeur", "Débit", "Libellé opération"]
    date_idx, amount_idx, label_idx = AccountingAgent._detect_csv_columns(headers)
    assert date_idx == 0
    assert amount_idx == 1
    assert label_idx == 2


def test_detect_csv_columns_missing_amount() -> None:
    headers = ["date", "reference"]
    date_idx, amount_idx, label_idx = AccountingAgent._detect_csv_columns(headers)
    assert date_idx == 0
    assert amount_idx is None


# ── _parse_bank_amount ─────────────────────────────────────────────────────────


def test_parse_bank_amount_positive() -> None:
    result = AccountingAgent._parse_bank_amount("142.50")
    assert result == pytest.approx(142.50)


def test_parse_bank_amount_comma_decimal() -> None:
    result = AccountingAgent._parse_bank_amount("142,50")
    assert result == pytest.approx(142.50)


def test_parse_bank_amount_negative() -> None:
    result = AccountingAgent._parse_bank_amount("-45.00")
    assert result == pytest.approx(-45.00)


def test_parse_bank_amount_with_currency_symbol() -> None:
    result = AccountingAgent._parse_bank_amount("99.99€")
    assert result == pytest.approx(99.99)


def test_parse_bank_amount_invalid_returns_none() -> None:
    result = AccountingAgent._parse_bank_amount("pas un montant")
    assert result is None


# ── _parse_bank_date ───────────────────────────────────────────────────────────


def test_parse_bank_date_iso() -> None:
    result = AccountingAgent._parse_bank_date("2026-03-15")
    assert result == datetime(2026, 3, 15)


def test_parse_bank_date_french() -> None:
    result = AccountingAgent._parse_bank_date("15/03/2026")
    assert result == datetime(2026, 3, 15)


def test_parse_bank_date_dotted() -> None:
    result = AccountingAgent._parse_bank_date("15.03.2026")
    assert result == datetime(2026, 3, 15)


def test_parse_bank_date_invalid_returns_none() -> None:
    result = AccountingAgent._parse_bank_date("pas-une-date")
    assert result is None


# ── _reconcile_with_bank ───────────────────────────────────────────────────────


def test_reconcile_exact_match(agent: AccountingAgent, tmp_path: Path) -> None:
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,montant,libelle\n2026-03-15,-142.50,EDF PAIEMENT\n", encoding="utf-8")

    invoices = [_make_invoice(vendor="EDF", date="2026-03-15", amount_ttc=142.50)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 1
    assert report["orphans"] == 0
    assert invoices[0].reconciliation_status == "RECONCILED"


def test_reconcile_orphan_no_match(agent: AccountingAgent, tmp_path: Path) -> None:
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,montant,libelle\n2026-03-15,-99.00,AUTRE\n", encoding="utf-8")

    invoices = [_make_invoice(vendor="EDF", date="2026-03-15", amount_ttc=142.50)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 0
    assert report["orphans"] == 1
    assert invoices[0].reconciliation_status == "ORPHAN"


def test_reconcile_date_tolerance_15_days(agent: AccountingAgent, tmp_path: Path) -> None:
    """Une facture du 15 mars doit matcher un virement du 25 mars (10 jours d'écart)."""
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,montant,libelle\n2026-03-25,-142.50,EDF\n", encoding="utf-8")

    invoices = [_make_invoice(vendor="EDF", date="2026-03-15", amount_ttc=142.50)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 1


def test_reconcile_date_outside_tolerance(agent: AccountingAgent, tmp_path: Path) -> None:
    """Un écart de 20 jours dépasse la tolérance de 15 jours → orphelin."""
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,montant,libelle\n2026-04-04,-142.50,EDF\n", encoding="utf-8")

    invoices = [_make_invoice(vendor="EDF", date="2026-03-15", amount_ttc=142.50)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 0
    assert report["orphans"] == 1


def test_reconcile_amount_tolerance_within(agent: AccountingAgent, tmp_path: Path) -> None:
    """Un écart de 0.01€ est dans la tolérance."""
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,montant,libelle\n2026-03-15,-142.51,EDF\n", encoding="utf-8")

    invoices = [_make_invoice(vendor="EDF", date="2026-03-15", amount_ttc=142.50)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 1


def test_reconcile_amount_tolerance_outside(agent: AccountingAgent, tmp_path: Path) -> None:
    """Un écart de 0.02€ dépasse la tolérance → orphelin."""
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,montant,libelle\n2026-03-15,-142.52,EDF\n", encoding="utf-8")

    invoices = [_make_invoice(vendor="EDF", date="2026-03-15", amount_ttc=142.50)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 0


def test_reconcile_invoice_without_date_is_orphan(agent: AccountingAgent, tmp_path: Path) -> None:
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,montant,libelle\n2026-03-15,-142.50,EDF\n", encoding="utf-8")

    inv = _make_invoice(date=None)  # type: ignore[arg-type]
    report = agent._reconcile_with_bank(str(csv_file), [inv])

    assert report["orphans"] == 1


def test_reconcile_invoice_without_amount_is_orphan(agent: AccountingAgent, tmp_path: Path) -> None:
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,montant,libelle\n2026-03-15,-142.50,EDF\n", encoding="utf-8")

    inv = _make_invoice(amount_ttc=None)  # type: ignore[arg-type]
    report = agent._reconcile_with_bank(str(csv_file), [inv])

    assert report["orphans"] == 1


def test_reconcile_semicolon_csv(agent: AccountingAgent, tmp_path: Path) -> None:
    """Gestion d'un CSV avec délimiteur point-virgule."""
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date;montant;libelle\n2026-03-15;-142.50;EDF\n", encoding="utf-8")

    invoices = [_make_invoice(vendor="EDF", date="2026-03-15", amount_ttc=142.50)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 1


def test_reconcile_ambiguous_multiple_candidates(agent: AccountingAgent, tmp_path: Path) -> None:
    """Si plusieurs lignes bancaires matchent la même facture, statut AMBIGUOUS."""
    csv_file = tmp_path / "bank.csv"
    # Deux lignes identiques en montant et date
    csv_file.write_text(
        "date,montant,libelle\n"
        "2026-03-15,-15.00,Leclerc A\n"
        "2026-03-15,-15.00,Leclerc B\n",
        encoding="utf-8",
    )

    invoices = [_make_invoice(vendor="Leclerc", date="2026-03-15", amount_ttc=15.00)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 0
    assert report.get("ambiguous", 0) == 1
    assert invoices[0].reconciliation_status == "AMBIGUOUS"


def test_reconcile_no_ambiguity_different_amounts(agent: AccountingAgent, tmp_path: Path) -> None:
    """Deux lignes bancaires de montants différents → pas d'ambiguïté."""
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text(
        "date,montant,libelle\n"
        "2026-03-15,-15.00,A\n"
        "2026-03-15,-20.00,B\n",
        encoding="utf-8",
    )

    invoices = [_make_invoice(vendor="X", date="2026-03-15", amount_ttc=15.00)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    assert report["reconciled"] == 1
    assert report.get("ambiguous", 0) == 0


def test_reconcile_float_precision_no_false_orphan(agent: AccountingAgent, tmp_path: Path) -> None:
    """
    Précision flottante : 0.1 + 0.2 doit matcher 0.3 sans créer un faux ORPHAN.
    Utilisation de Decimal pour éviter les erreurs de représentation float.
    """
    csv_file = tmp_path / "bank.csv"
    # 0.1 + 0.2 = 0.30000000000000004 en float — Decimal évite ça
    csv_file.write_text("date,montant,libelle\n2026-03-01,-0.30,test\n", encoding="utf-8")

    # amount_ttc calculé comme 0.1 + 0.2 → potentiellement 0.30000000000000004
    amount = 0.1 + 0.2  # == 0.30000000000000004 en float
    invoices = [_make_invoice(vendor="Test", date="2026-03-01", amount_ttc=amount)]
    report = agent._reconcile_with_bank(str(csv_file), invoices)

    # Avec Decimal(str(amount)), on compare "0.30000000000000004" vs "0.3"
    # La différence absolue = 0.000...4 < 0.01 → doit être RECONCILED
    assert report["reconciled"] == 1


# ── Batch complet avec 5 factures mock ────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_batch_five_invoices(agent: AccountingAgent, tmp_path: Path) -> None:
    """Traitement batch de 5 factures PDF mock avec LLM simulé."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    # Créer 5 faux fichiers PDF (vides — l'extraction texte est mockée)
    mock_vendors = [
        ("EDF", "2026-03-01", 142.50, "Energie"),
        ("SNCF", "2026-03-05", 45.00, "Transport"),
        ("Orange", "2026-03-10", 29.99, "Telecom"),
        ("Leclerc", "2026-03-12", 87.30, "Restauration"),
        ("AXA", "2026-03-15", 210.00, "Assurance"),
    ]

    for i, (vendor, date, amount, cat) in enumerate(mock_vendors):
        (input_dir / f"facture_{i+1}.pdf").write_bytes(b"%PDF-1.4 mock")

    # Mock de l'extraction de texte et du LLM
    def fake_extract(path: Path) -> str:
        return "Facture fournisseur exemple montant 100 EUR date 2026-03-01"

    def fake_llm_generate(**kwargs: Any) -> str:
        idx = 0
        # Déduire l'index depuis le prompt si possible
        prompt = kwargs.get("prompt", "")
        for i, (vendor, date, amount, cat) in enumerate(mock_vendors):
            if str(i + 1) in str(prompt) or vendor.lower() in prompt.lower():
                idx = i
                break
        vendor, date, amount, cat = mock_vendors[idx % len(mock_vendors)]
        return json.dumps({
            "vendor": vendor, "date": date,
            "amount_ttc": amount, "vat_amount": round(amount * 0.2 / 1.2, 2),
            "category": cat,
        })

    agent.llm.generate = MagicMock(side_effect=fake_llm_generate)

    with patch.object(agent, "_extract_text", side_effect=fake_extract):
        report = await agent._tool_process_batch(
            input_folder=str(input_dir),
            output_folder=str(output_dir),
        )

    assert "Rapport de traitement comptable" in report
    assert "Traitement 100% local" in report
    # Le rapport doit mentionner 5 fichiers analysés
    assert "5" in report


@pytest.mark.asyncio
async def test_process_batch_empty_folder(agent: AccountingAgent, tmp_path: Path) -> None:
    """Un dossier vide renvoie un message d'erreur sans crash."""
    input_dir = tmp_path / "vide"
    input_dir.mkdir()
    output_dir = tmp_path / "output"

    result = await agent._tool_process_batch(
        input_folder=str(input_dir),
        output_folder=str(output_dir),
    )
    assert "Aucun fichier supporté" in result


@pytest.mark.asyncio
async def test_process_batch_missing_folder(agent: AccountingAgent, tmp_path: Path) -> None:
    """Un dossier source inexistant renvoie une erreur propre."""
    result = await agent._tool_process_batch(
        input_folder="/chemin/inexistant/xyz",
        output_folder=str(tmp_path / "output"),
    )
    assert "introuvable" in result.lower()


# ── get_tools ─────────────────────────────────────────────────────────────────


def test_get_tools_returns_four(agent: AccountingAgent) -> None:
    tools = agent.get_tools()
    names = {t.name for t in tools}
    assert names == {"process_batch", "extract_invoice", "reconcile", "export_fec"}


def test_valid_categories_count() -> None:
    """S'assure que les 9 catégories prévues dans le spec sont bien présentes."""
    expected = {
        "Energie", "Restauration", "Transport", "Fournitures",
        "Telecom", "Loyer", "Assurance", "Honoraires", "Autre",
    }
    assert expected == _VALID_CATEGORIES
