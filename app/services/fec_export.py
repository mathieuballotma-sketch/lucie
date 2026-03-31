"""
FEC Export — Fichier des Écritures Comptables.

Génère un fichier FEC conforme au format DGFiP (article A.47 A-1 du LPF).
Format obligatoire pour toute entreprise soumise au contrôle fiscal en France.

Spécification FEC :
  - Encodage : UTF-8 (ou ISO-8859-15)
  - Délimiteur : tabulation (\\t) ou pipe (|)
  - 18 colonnes obligatoires
  - Nom du fichier : {SIREN}FEC{YYYYMMDD}.txt

Colonnes obligatoires (ordre strict) :
  1. JournalCode          — Code du journal (ACH, VTE, BQ, OD...)
  2. JournalLib           — Libellé du journal
  3. EcritureNum          — Numéro d'écriture séquentiel
  4. EcritureDate         — Date d'écriture (YYYYMMDD)
  5. CompteNum            — Numéro de compte (PCG)
  6. CompteLib            — Libellé du compte
  7. CompAuxNum           — Numéro auxiliaire (fournisseur/client)
  8. CompAuxLib           — Libellé auxiliaire
  9. PieceRef             — Référence de la pièce
  10. PieceDate           — Date de la pièce (YYYYMMDD)
  11. EcritureLib         — Libellé de l'écriture
  12. Debit               — Montant débit (séparateur décimal = virgule)
  13. Credit              — Montant crédit (séparateur décimal = virgule)
  14. EcrtureLettrage     — Code de lettrage
  15. DateLettrage        — Date de lettrage (YYYYMMDD)
  16. ValidDate           — Date de validation (YYYYMMDD)
  17. Montantdevise       — Montant en devise
  18. Idevise             — Code devise (EUR)
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils.logger import logger

# ── Plan Comptable Général — mapping catégories → comptes ────────────

# Comptes de charges (classe 6) les plus courants pour les catégories Lucie
_CATEGORY_TO_ACCOUNT: Dict[str, Tuple[str, str]] = {
    "Energie": ("6061", "Fournitures non stockables - Eau, énergie"),
    "Restauration": ("6256", "Missions - Repas"),
    "Transport": ("6251", "Voyages et déplacements"),
    "Fournitures": ("6063", "Fournitures d'entretien et petit équipement"),
    "Telecom": ("6262", "Frais de télécommunications"),
    "Loyer": ("6132", "Locations immobilières"),
    "Assurance": ("6161", "Assurances multirisques"),
    "Honoraires": ("6226", "Honoraires"),
    "Autre": ("6288", "Autres services extérieurs divers"),
}

# Compte de TVA déductible
_TVA_DEDUCTIBLE = ("44566", "TVA déductible sur autres biens et services")

# Compte fournisseur générique
_FOURNISSEUR_COMPTE = ("401000", "Fournisseurs")

# Journaux
_JOURNAL_ACHATS = ("ACH", "Journal des achats")
_JOURNAL_BANQUE = ("BQ", "Journal de banque")


@dataclass
class FECEntry:
    """Une ligne d'écriture comptable FEC."""
    journal_code: str
    journal_lib: str
    ecriture_num: str
    ecriture_date: str       # YYYYMMDD
    compte_num: str
    compte_lib: str
    comp_aux_num: str = ""
    comp_aux_lib: str = ""
    piece_ref: str = ""
    piece_date: str = ""     # YYYYMMDD
    ecriture_lib: str = ""
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    lettrage: str = ""
    date_lettrage: str = ""  # YYYYMMDD
    valid_date: str = ""     # YYYYMMDD
    montant_devise: Decimal = Decimal("0")
    idevise: str = "EUR"

    def to_fec_row(self) -> List[str]:
        """Sérialise en ligne FEC (18 colonnes, virgule décimale)."""
        def fmt_dec(d: Decimal) -> str:
            """Format Decimal avec virgule comme séparateur décimal."""
            quantized = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return str(quantized).replace(".", ",")

        return [
            self.journal_code,
            self.journal_lib,
            self.ecriture_num,
            self.ecriture_date,
            self.compte_num,
            self.compte_lib,
            self.comp_aux_num,
            self.comp_aux_lib,
            self.piece_ref,
            self.piece_date,
            self.ecriture_lib,
            fmt_dec(self.debit),
            fmt_dec(self.credit),
            self.lettrage,
            self.date_lettrage,
            self.valid_date,
            fmt_dec(self.montant_devise),
            self.idevise,
        ]


# ── En-tête officiel FEC ─────────────────────────────────────────────

FEC_HEADER = [
    "JournalCode", "JournalLib", "EcritureNum", "EcritureDate",
    "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
    "PieceRef", "PieceDate", "EcritureLib",
    "Debit", "Credit", "EcrtureLettrage", "DateLettrage",
    "ValidDate", "Montantdevise", "Idevise",
]


@dataclass
class FECInvoice:
    """Données minimales d'une facture pour générer les écritures FEC."""
    vendor: str
    date: str                # YYYY-MM-DD
    amount_ttc: Decimal
    vat_amount: Optional[Decimal] = None
    category: str = "Autre"
    piece_ref: str = ""
    reconciled: bool = False

    @property
    def amount_ht(self) -> Decimal:
        """Montant hors taxes."""
        if self.vat_amount is not None:
            return self.amount_ttc - self.vat_amount
        return self.amount_ttc

    @property
    def effective_vat(self) -> Decimal:
        """TVA effective (0 si absente)."""
        return self.vat_amount if self.vat_amount is not None else Decimal("0")


class FECExporter:
    """
    Générateur de fichiers FEC conformes DGFiP.

    Pour chaque facture, génère les écritures comptables :
      1. Débit du compte de charge (6xxx) pour le montant HT
      2. Débit du compte TVA (44566) pour la TVA
      3. Crédit du compte fournisseur (401000) pour le TTC

    Si la facture est réconciliée avec la banque :
      4. Débit du compte fournisseur (401000)
      5. Crédit du compte banque (512000)
    """

    def __init__(
        self,
        siren: str = "000000000",
        exercice_start: Optional[str] = None,
        delimiter: str = "\t",
    ) -> None:
        self.siren = siren
        self.exercice_start = exercice_start or datetime.now().strftime("%Y0101")
        self.delimiter = delimiter
        self._counter = 0
        self._entries: List[FECEntry] = []

    def _next_num(self) -> str:
        """Numéro d'écriture séquentiel."""
        self._counter += 1
        return f"ACH{self._counter:06d}"

    def _format_date(self, date_str: str) -> str:
        """Convertit YYYY-MM-DD en YYYYMMDD pour le FEC."""
        return date_str.replace("-", "")

    def _sanitize_lib(self, text: str) -> str:
        """Nettoie un libellé pour le FEC (pas de tab, pas de pipe)."""
        cleaned = text.replace("\t", " ").replace("|", " ").strip()
        return cleaned[:100]  # Max 100 chars

    def add_invoice(self, invoice: FECInvoice) -> None:
        """
        Ajoute les écritures comptables pour une facture.

        Schéma d'écriture (journal ACH) :
        - Débit 6xxx (charge HT)
        - Débit 44566 (TVA déductible)
        - Crédit 401000 (fournisseur TTC)
        """
        num = self._next_num()
        date_fec = self._format_date(invoice.date)
        vendor_clean = self._sanitize_lib(invoice.vendor)
        lib = f"Facture {vendor_clean}"

        charge_account, charge_lib = _CATEGORY_TO_ACCOUNT.get(
            invoice.category, _CATEGORY_TO_ACCOUNT["Autre"]
        )
        tva_account, tva_lib = _TVA_DEDUCTIBLE
        fourn_account, fourn_lib = _FOURNISSEUR_COMPTE

        # Écriture 1 : Débit compte de charge (HT)
        self._entries.append(FECEntry(
            journal_code=_JOURNAL_ACHATS[0],
            journal_lib=_JOURNAL_ACHATS[1],
            ecriture_num=num,
            ecriture_date=date_fec,
            compte_num=charge_account,
            compte_lib=charge_lib,
            comp_aux_num="",
            comp_aux_lib="",
            piece_ref=invoice.piece_ref or num,
            piece_date=date_fec,
            ecriture_lib=lib,
            debit=invoice.amount_ht,
            credit=Decimal("0"),
            valid_date=date_fec,
            idevise="EUR",
        ))

        # Écriture 2 : Débit TVA déductible (si TVA > 0)
        if invoice.effective_vat > 0:
            self._entries.append(FECEntry(
                journal_code=_JOURNAL_ACHATS[0],
                journal_lib=_JOURNAL_ACHATS[1],
                ecriture_num=num,
                ecriture_date=date_fec,
                compte_num=tva_account,
                compte_lib=tva_lib,
                piece_ref=invoice.piece_ref or num,
                piece_date=date_fec,
                ecriture_lib=f"TVA {vendor_clean}",
                debit=invoice.effective_vat,
                credit=Decimal("0"),
                valid_date=date_fec,
                idevise="EUR",
            ))

        # Écriture 3 : Crédit fournisseur (TTC)
        vendor_aux = re.sub(r"[^A-Z0-9]", "", vendor_clean.upper())[:8]
        self._entries.append(FECEntry(
            journal_code=_JOURNAL_ACHATS[0],
            journal_lib=_JOURNAL_ACHATS[1],
            ecriture_num=num,
            ecriture_date=date_fec,
            compte_num=fourn_account,
            compte_lib=fourn_lib,
            comp_aux_num=f"F_{vendor_aux}" if vendor_aux else "",
            comp_aux_lib=vendor_clean,
            piece_ref=invoice.piece_ref or num,
            piece_date=date_fec,
            ecriture_lib=lib,
            debit=Decimal("0"),
            credit=invoice.amount_ttc,
            valid_date=date_fec,
            idevise="EUR",
        ))

        # Si réconciliée : écriture de paiement (journal BQ)
        if invoice.reconciled:
            pay_num = self._next_num()
            self._entries.append(FECEntry(
                journal_code=_JOURNAL_BANQUE[0],
                journal_lib=_JOURNAL_BANQUE[1],
                ecriture_num=pay_num,
                ecriture_date=date_fec,
                compte_num=fourn_account,
                compte_lib=fourn_lib,
                comp_aux_num=f"F_{vendor_aux}" if vendor_aux else "",
                comp_aux_lib=vendor_clean,
                piece_ref=invoice.piece_ref or pay_num,
                piece_date=date_fec,
                ecriture_lib=f"Paiement {vendor_clean}",
                debit=invoice.amount_ttc,
                credit=Decimal("0"),
                lettrage=f"L{num[-4:]}",
                valid_date=date_fec,
                idevise="EUR",
            ))
            self._entries.append(FECEntry(
                journal_code=_JOURNAL_BANQUE[0],
                journal_lib=_JOURNAL_BANQUE[1],
                ecriture_num=pay_num,
                ecriture_date=date_fec,
                compte_num="512000",
                compte_lib="Banque",
                piece_ref=invoice.piece_ref or pay_num,
                piece_date=date_fec,
                ecriture_lib=f"Paiement {vendor_clean}",
                debit=Decimal("0"),
                credit=invoice.amount_ttc,
                lettrage=f"L{num[-4:]}",
                valid_date=date_fec,
                idevise="EUR",
            ))

    def validate(self) -> List[str]:
        """
        Valide les écritures FEC avant export.

        Vérifie :
        - Équilibre débit/crédit par écriture
        - Présence des champs obligatoires
        - Format des dates
        """
        errors: List[str] = []

        # Grouper par numéro d'écriture
        by_num: Dict[str, List[FECEntry]] = {}
        for entry in self._entries:
            by_num.setdefault(entry.ecriture_num, []).append(entry)

        for num, entries in by_num.items():
            total_debit = sum(e.debit for e in entries)
            total_credit = sum(e.credit for e in entries)
            diff = abs(total_debit - total_credit)
            if diff > Decimal("0.01"):
                errors.append(
                    f"Ecriture {num}: desequilibre debit={total_debit} credit={total_credit} "
                    f"(diff={diff})"
                )

            for entry in entries:
                if not entry.ecriture_date or len(entry.ecriture_date) != 8:
                    errors.append(f"Ecriture {num}: date invalide '{entry.ecriture_date}'")
                if not entry.compte_num:
                    errors.append(f"Ecriture {num}: compte_num manquant")

        return errors

    def export(self, output_path: Optional[str] = None) -> str:
        """
        Exporte le fichier FEC.

        Args:
            output_path: Chemin de sortie. Si None, retourne le contenu.

        Returns:
            Le contenu du fichier FEC ou le chemin du fichier écrit.
        """
        validation_errors = self.validate()
        if validation_errors:
            logger.warning(f"FEC validation: {len(validation_errors)} erreurs")
            for err in validation_errors:
                logger.warning(f"  - {err}")

        # Trier les écritures par date puis numéro
        sorted_entries = sorted(
            self._entries,
            key=lambda e: (e.ecriture_date, e.ecriture_num),
        )

        # Générer le contenu
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=self.delimiter, lineterminator="\n")
        writer.writerow(FEC_HEADER)
        for entry in sorted_entries:
            writer.writerow(entry.to_fec_row())

        content = buf.getvalue()

        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            logger.info(f"FEC exporte: {path} ({len(sorted_entries)} ecritures)")
            return str(path)

        return content

    def generate_filename(self, close_date: Optional[str] = None) -> str:
        """
        Génère le nom de fichier FEC conforme DGFiP.
        Format : {SIREN}FEC{YYYYMMDD}.txt
        """
        date = close_date or datetime.now().strftime("%Y%m%d")
        return f"{self.siren}FEC{date}.txt"

    @property
    def entry_count(self) -> int:
        """Nombre d'écritures."""
        return len(self._entries)

    @property
    def entries(self) -> List[FECEntry]:
        """Accès aux écritures (lecture seule)."""
        return list(self._entries)

    def summary(self) -> Dict[str, Any]:
        """Résumé de l'export FEC."""
        total_debit = sum(e.debit for e in self._entries)
        total_credit = sum(e.credit for e in self._entries)

        # Compter les écritures uniques
        unique_nums = {e.ecriture_num for e in self._entries}

        return {
            "siren": self.siren,
            "total_entries": len(self._entries),
            "unique_ecritures": len(unique_nums),
            "total_debit": str(total_debit.quantize(Decimal("0.01"))),
            "total_credit": str(total_credit.quantize(Decimal("0.01"))),
            "balanced": abs(total_debit - total_credit) < Decimal("0.01"),
            "validation_errors": self.validate(),
        }
