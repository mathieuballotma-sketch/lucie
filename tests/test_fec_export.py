"""
Tests unitaires pour le module FEC Export.

Couvre :
  - FECEntry sérialisation
  - FECExporter: ajout facture, écritures correctes, équilibre D/C
  - FEC avec TVA et sans TVA
  - FEC avec factures réconciliées (écritures de paiement)
  - Validation (équilibre, dates, comptes)
  - Export vers fichier et contenu
  - Nom de fichier conforme DGFiP
  - Summary
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.fec_export import (
    FECEntry, FECExporter, FECInvoice, FEC_HEADER,
    _CATEGORY_TO_ACCOUNT, _TVA_DEDUCTIBLE, _FOURNISSEUR_COMPTE,
)


# ── FECEntry ─────────────────────────────────────────────────────────


class TestFECEntry:

    def test_to_fec_row_length(self):
        """Une ligne FEC a exactement 18 colonnes."""
        entry = FECEntry(
            journal_code="ACH", journal_lib="Journal des achats",
            ecriture_num="ACH000001", ecriture_date="20260315",
            compte_num="6061", compte_lib="Energie",
            debit=Decimal("100.00"), credit=Decimal("0"),
        )
        row = entry.to_fec_row()
        assert len(row) == 18

    def test_decimal_comma_format(self):
        """Les montants utilisent la virgule comme séparateur décimal."""
        entry = FECEntry(
            journal_code="ACH", journal_lib="",
            ecriture_num="001", ecriture_date="20260101",
            compte_num="6061", compte_lib="",
            debit=Decimal("1234.56"), credit=Decimal("0"),
        )
        row = entry.to_fec_row()
        assert row[11] == "1234,56"  # Debit
        assert row[12] == "0,00"     # Credit


# ── FECInvoice ───────────────────────────────────────────────────────


class TestFECInvoice:

    def test_amount_ht_with_vat(self):
        inv = FECInvoice(vendor="EDF", date="2026-03-15",
                        amount_ttc=Decimal("120"), vat_amount=Decimal("20"))
        assert inv.amount_ht == Decimal("100")

    def test_amount_ht_without_vat(self):
        inv = FECInvoice(vendor="EDF", date="2026-03-15",
                        amount_ttc=Decimal("120"), vat_amount=None)
        assert inv.amount_ht == Decimal("120")

    def test_effective_vat_none(self):
        inv = FECInvoice(vendor="EDF", date="2026-03-15",
                        amount_ttc=Decimal("120"), vat_amount=None)
        assert inv.effective_vat == Decimal("0")


# ── FECExporter ──────────────────────────────────────────────────────


class TestFECExporter:

    def _make_invoice(self, **kwargs):
        defaults = dict(
            vendor="EDF", date="2026-03-15",
            amount_ttc=Decimal("142.50"),
            vat_amount=Decimal("23.75"),
            category="Energie",
        )
        defaults.update(kwargs)
        return FECInvoice(**defaults)

    def test_add_invoice_creates_entries(self):
        """Une facture avec TVA génère 3 écritures."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice())
        # 3 lignes : charge HT + TVA + fournisseur TTC
        assert exp.entry_count == 3

    def test_add_invoice_without_vat(self):
        """Une facture sans TVA génère 2 écritures (pas de ligne TVA)."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(vat_amount=None))
        assert exp.entry_count == 2

    def test_add_invoice_with_zero_vat(self):
        """TVA = 0 → pas de ligne TVA."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(vat_amount=Decimal("0")))
        assert exp.entry_count == 2

    def test_balance_debit_credit(self):
        """Total débit = total crédit pour chaque écriture."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice())
        errors = exp.validate()
        assert len(errors) == 0, f"Erreurs: {errors}"

    def test_balance_multiple_invoices(self):
        """Plusieurs factures → toujours équilibré."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(vendor="EDF", amount_ttc=Decimal("142.50"), vat_amount=Decimal("23.75")))
        exp.add_invoice(self._make_invoice(vendor="SNCF", amount_ttc=Decimal("45.00"), vat_amount=Decimal("7.50"), category="Transport"))
        exp.add_invoice(self._make_invoice(vendor="Free", amount_ttc=Decimal("29.99"), vat_amount=None, category="Telecom"))
        errors = exp.validate()
        assert len(errors) == 0

    def test_correct_accounts_energie(self):
        """Catégorie Energie → compte 6061."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(category="Energie"))
        charge_entry = [e for e in exp.entries if e.compte_num == "6061"]
        assert len(charge_entry) == 1

    def test_correct_accounts_transport(self):
        """Catégorie Transport → compte 6251."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(category="Transport"))
        charge_entry = [e for e in exp.entries if e.compte_num == "6251"]
        assert len(charge_entry) == 1

    def test_reconciled_invoice_adds_payment(self):
        """Facture réconciliée → 2 écritures supplémentaires (paiement BQ)."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(reconciled=True))
        # 3 (achat) + 2 (paiement) = 5
        assert exp.entry_count == 5

    def test_reconciled_payment_balanced(self):
        """Écritures de paiement aussi équilibrées."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(reconciled=True))
        errors = exp.validate()
        assert len(errors) == 0

    def test_export_content_has_header(self):
        """Le contenu FEC commence par l'en-tête."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice())
        content = exp.export()
        first_line = content.split("\n")[0]
        assert "JournalCode" in first_line
        assert "EcritureDate" in first_line

    def test_export_content_tab_delimited(self):
        """Le FEC est délimité par tabulation par défaut."""
        exp = FECExporter(delimiter="\t")
        exp.add_invoice(self._make_invoice())
        content = exp.export()
        lines = content.strip().split("\n")
        # Header
        assert "\t" in lines[0]
        # Au moins 18 colonnes
        assert len(lines[0].split("\t")) == 18

    def test_export_to_file(self):
        """Export écrit un fichier sur disque."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice())
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_fec.txt")
            result = exp.export(output_path=path)
            assert os.path.exists(result)
            content = Path(result).read_text(encoding="utf-8")
            assert "JournalCode" in content

    def test_generate_filename(self):
        """Nom de fichier conforme DGFiP."""
        exp = FECExporter(siren="123456789")
        filename = exp.generate_filename("20260331")
        assert filename == "123456789FEC20260331.txt"

    def test_generate_filename_default_date(self):
        """Sans date, utilise la date du jour."""
        exp = FECExporter(siren="999888777")
        filename = exp.generate_filename()
        assert filename.startswith("999888777FEC")
        assert filename.endswith(".txt")

    def test_summary(self):
        """Summary retourne les bonnes données."""
        exp = FECExporter(siren="123456789")
        exp.add_invoice(self._make_invoice())
        summary = exp.summary()
        assert summary["siren"] == "123456789"
        assert summary["total_entries"] == 3
        assert summary["balanced"] is True

    def test_date_format_yyyymmdd(self):
        """Les dates FEC sont au format YYYYMMDD."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(date="2026-03-15"))
        for entry in exp.entries:
            if entry.ecriture_date:
                assert len(entry.ecriture_date) == 8
                assert entry.ecriture_date == "20260315"

    def test_ecriture_num_sequential(self):
        """Numéros d'écriture séquentiels."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(vendor="A"))
        exp.add_invoice(self._make_invoice(vendor="B"))
        nums = sorted({e.ecriture_num for e in exp.entries})
        assert len(nums) == 2  # 2 factures = 2 numéros d'écriture
        assert nums[0] < nums[1]

    def test_fournisseur_auxiliaire(self):
        """Le compte auxiliaire fournisseur est correctement renseigné."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(vendor="Orange"))
        fourn_entries = [e for e in exp.entries if e.compte_num == "401000"]
        assert len(fourn_entries) == 1
        assert fourn_entries[0].comp_aux_lib == "Orange"
        assert fourn_entries[0].comp_aux_num.startswith("F_")

    def test_multiple_categories_different_accounts(self):
        """Chaque catégorie utilise le bon compte de charge."""
        exp = FECExporter()
        exp.add_invoice(self._make_invoice(category="Energie", vendor="EDF"))
        exp.add_invoice(self._make_invoice(category="Telecom", vendor="Free"))
        exp.add_invoice(self._make_invoice(category="Loyer", vendor="Bureau"))

        accounts = {e.compte_num for e in exp.entries if e.debit > 0 and e.journal_code == "ACH"}
        assert "6061" in accounts  # Energie
        assert "6262" in accounts  # Telecom
        assert "6132" in accounts  # Loyer

    def test_all_categories_mapped(self):
        """Toutes les catégories Lucie ont un mapping comptable."""
        expected = {"Energie", "Restauration", "Transport", "Fournitures",
                    "Telecom", "Loyer", "Assurance", "Honoraires", "Autre"}
        assert set(_CATEGORY_TO_ACCOUNT.keys()) == expected
