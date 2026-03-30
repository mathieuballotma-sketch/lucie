"""
AccountingAgent — Agent de comptabilité pour l'extraction et la classification de factures.
MVP monétisable : orchestre pdfplumber + LLM + classement arborescent.

Fonctionnalités :
  - Extraction de texte depuis PDF (pdfplumber), Word (python-docx) et images (pytesseract)
  - Extraction JSON structurée via LLM (vendor, date, montant, TVA, catégorie)
  - Renommage automatique : YYYY-MM-DD_Vendor_MontantTTC.ext
  - Classement arborescent : /Compta/YYYY/Categorie/fichier
  - Réconciliation avec export CSV bancaire (tolérance ±0.01€ et ±15 jours)
  - Rapport Markdown final avec statut de chaque facture
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
import shutil
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic.v1 import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


# Extensions supportées pour l'extraction de texte
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tiff", ".bmp",
})

# Catégories de factures valides
_VALID_CATEGORIES: frozenset[str] = frozenset({
    "Energie", "Restauration", "Transport", "Fournitures",
    "Telecom", "Loyer", "Assurance", "Honoraires", "Autre",
})

# Délimiteurs CSV à tester (ordre de priorité)
_CSV_DELIMITERS = (",", ";", "\t")


# ── Contracts Pydantic ────────────────────────────────────────────────────────

class ProcessBatchContract(BaseModel):
    """Contrat pour le traitement d'un lot de factures."""

    input_folder: str = Field(..., description="Dossier source contenant les factures")
    output_folder: str = Field(..., description="Dossier cible pour les factures classées")
    bank_csv: Optional[str] = Field(None, description="Chemin vers l'export CSV bancaire (optionnel)")


class ExtractInvoiceContract(BaseModel):
    """Contrat pour l'extraction d'une facture individuelle."""

    file_path: str = Field(..., description="Chemin vers le fichier facture (PDF, DOCX, image)")


class ReconcileContract(BaseModel):
    """Contrat pour la réconciliation bancaire."""

    csv_path: str = Field(..., description="Chemin vers l'export CSV bancaire")
    invoices_json: str = Field(..., description="JSON des factures extraites (liste)")


# ── Structure de données interne ──────────────────────────────────────────────

class InvoiceData:
    """Données structurées d'une facture extraite."""

    __slots__ = (
        "vendor", "date", "amount_ttc", "vat_amount",
        "category", "source_path", "output_path", "reconciliation_status",
    )

    def __init__(
        self,
        vendor: Optional[str],
        date: Optional[str],
        amount_ttc: Optional[float],
        vat_amount: Optional[float],
        category: str,
        source_path: str,
        output_path: Optional[str] = None,
        reconciliation_status: str = "PENDING",
    ) -> None:
        self.vendor = vendor
        self.date = date
        self.amount_ttc = amount_ttc
        self.vat_amount = vat_amount
        self.category = category
        self.source_path = source_path
        self.output_path = output_path
        self.reconciliation_status = reconciliation_status

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la facture en dictionnaire."""
        return {
            "vendor": self.vendor,
            "date": self.date,
            "amount_ttc": self.amount_ttc,
            "vat_amount": self.vat_amount,
            "category": self.category,
            "source_path": self.source_path,
            "output_path": self.output_path,
            "reconciliation_status": self.reconciliation_status,
        }


# ── Agent principal ───────────────────────────────────────────────────────────

class AccountingAgent(BaseAgent):
    """
    Agent de comptabilité — extraction, classification et réconciliation de factures.

    Orchestre :
    - pdfplumber / python-docx pour l'extraction de texte
    - LLM (model_role="generation") pour l'extraction JSON structurée
    - Classement arborescent automatique dans /Compta/YYYY/Categorie/

    Toutes les données restent locales — aucune donnée envoyée sur internet.
    """

    model_role = "generation"
    stability = "core"

    # Nombre de fichiers traités en parallèle
    _MAX_CONCURRENCY = 4

    def __init__(self, llm_service: Any, bus: Any, config: Dict[str, Any]) -> None:
        super().__init__("AccountingAgent", llm_service, bus)
        # Semaphore pour limiter la concurrence sur les appels LLM
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(self._MAX_CONCURRENCY)
        logger.info("🧾 AccountingAgent initialisé — traitement 100% local")

    # ── can_handle ────────────────────────────────────────────────────────────

    def can_handle(self, query: str) -> bool:
        """Détecte les requêtes liées à la comptabilité et aux factures."""
        keywords = [
            "facture", "comptabilité", "compta", "comptable",
            "tva", "montant ttc", "réconciliation", "rapprochement",
            "accounting", "invoice", "dépense", "fournisseur",
            "classer les factures", "traiter les factures",
        ]
        q = query.lower()
        return any(kw in q for kw in keywords)

    # ── Tools disponibles ─────────────────────────────────────────────────────

    def get_tools(self) -> List[Tool]:
        """Retourne les outils disponibles pour l'agent comptable."""
        return [
            Tool(
                name="process_batch",
                description=(
                    "Traite un lot de factures : extraction, renommage, classement "
                    "et réconciliation bancaire optionnelle"
                ),
                contract=ProcessBatchContract,
            ),
            Tool(
                name="extract_invoice",
                description="Extrait les données structurées d'une facture (PDF, DOCX, image)",
                contract=ExtractInvoiceContract,
            ),
            Tool(
                name="reconcile",
                description="Réconcilie les factures extraites avec un export CSV bancaire",
                contract=ReconcileContract,
            ),
        ]

    # ── Extraction de texte ───────────────────────────────────────────────────

    def _extract_text_from_pdf(self, file_path: Path) -> str:
        """Extrait le texte d'un fichier PDF via pdfplumber."""
        try:
            import pdfplumber

            with pdfplumber.open(str(file_path)) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                return "\n".join(pages)
        except ImportError:
            logger.warning("pdfplumber non disponible — extraction PDF ignorée")
            return ""
        except Exception as e:
            logger.error(f"Erreur extraction PDF {file_path.name} : {e}")
            return ""

    def _extract_text_from_docx(self, file_path: Path) -> str:
        """Extrait le texte d'un fichier Word via python-docx."""
        try:
            import docx

            document = docx.Document(str(file_path))
            paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)
        except ImportError:
            logger.warning("python-docx non disponible — extraction DOCX ignorée")
            return ""
        except Exception as e:
            logger.error(f"Erreur extraction DOCX {file_path.name} : {e}")
            return ""

    def _extract_text_from_image(self, file_path: Path) -> str:
        """Tente l'extraction OCR via pytesseract (optionnel)."""
        try:
            import pytesseract
            from PIL import Image

            image = Image.open(str(file_path))
            text: str = pytesseract.image_to_string(image, lang="fra")
            return text
        except ImportError:
            logger.debug("pytesseract/PIL non disponible — images non extraites")
            return ""
        except Exception as e:
            logger.error(f"Erreur OCR {file_path.name} : {e}")
            return ""

    def _extract_text(self, file_path: Path) -> str:
        """Dispatch l'extraction de texte selon le type de fichier."""
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_text_from_pdf(file_path)
        elif suffix in {".docx", ".doc"}:
            return self._extract_text_from_docx(file_path)
        elif suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}:
            return self._extract_text_from_image(file_path)
        else:
            logger.warning(f"Format non supporté : {suffix}")
            return ""

    # ── Extraction LLM ────────────────────────────────────────────────────────

    @staticmethod
    def _build_extraction_prompt(text: str) -> str:
        """Construit le prompt d'extraction JSON strict pour le LLM."""
        return (
            "Tu es un assistant comptable expert. Analyse ce texte de facture "
            "et extrait les informations clés.\n\n"
            "Réponds UNIQUEMENT avec un JSON valide, sans texte avant ni après :\n"
            "{\n"
            '  "vendor": "Nom du fournisseur ou null",\n'
            '  "date": "YYYY-MM-DD ou null",\n'
            '  "amount_ttc": 0.00,\n'
            '  "vat_amount": 0.00,\n'
            '  "category": '
            '"Energie|Restauration|Transport|Fournitures|Telecom|Loyer|Assurance|Honoraires|Autre"\n'
            "}\n\n"
            f"Texte de la facture :\n{text[:3000]}"
        )

    @staticmethod
    def _parse_invoice_json(response: str) -> Optional[Dict[str, Any]]:
        """
        Parse la réponse LLM pour extraire le JSON de facture.

        Stratégie en trois passes :
        1. Tentative directe après nettoyage des balises Markdown
        2. Extraction par comptage d'accolades (gère le texte autour du JSON)
        3. Regex simple sur la première occurrence de {...}
        """
        # Passe 1 — nettoyer les blocs Markdown et tenter json.loads directement
        cleaned = re.sub(r"```json\s*", "", response.strip())
        cleaned = re.sub(r"```\s*", "", cleaned).strip()

        try:
            return dict(json.loads(cleaned))
        except json.JSONDecodeError:
            pass

        # Passe 2 — brace-counting : extrait le premier bloc {...} complet
        # Gère les objets imbriqués et les chaînes contenant des accolades
        start = cleaned.find("{")
        while start != -1:
            depth = 0
            in_string = False
            escape_next = False
            end = start
            for i in range(start, len(cleaned)):
                ch = cleaned[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\" and in_string:
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        candidate = cleaned[start : end + 1]
                        try:
                            return dict(json.loads(candidate))
                        except json.JSONDecodeError:
                            break
            start = cleaned.find("{", start + 1)

        # Passe 3 — regex de secours sur le premier {...} sans imbrication
        match = re.search(r"\{[^{}]+\}", cleaned, re.DOTALL)
        if match:
            try:
                return dict(json.loads(match.group(0)))
            except json.JSONDecodeError:
                pass

        logger.warning(f"Impossible de parser la réponse LLM : {response[:200]}")
        return None

    @staticmethod
    def _normalize_invoice_data(raw: Dict[str, Any], source_path: str) -> "InvoiceData":
        """Normalise et valide les données JSON extraites par le LLM."""
        # Fournisseur
        vendor: Optional[str] = raw.get("vendor")
        if isinstance(vendor, str) and vendor.lower() in {"null", "none", ""}:
            vendor = None

        # Date — validation format YYYY-MM-DD
        date_str: Optional[str] = None
        raw_date = raw.get("date")
        if isinstance(raw_date, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
            date_str = raw_date

        # Montant TTC
        amount_ttc: Optional[float] = None
        raw_amount = raw.get("amount_ttc")
        if raw_amount is not None:
            try:
                amount_ttc = float(raw_amount)
            except (ValueError, TypeError):
                pass

        # TVA
        vat_amount: Optional[float] = None
        raw_vat = raw.get("vat_amount")
        if raw_vat is not None:
            try:
                vat_amount = float(raw_vat)
            except (ValueError, TypeError):
                pass

        # Catégorie
        category = str(raw.get("category", "Autre"))
        if category not in _VALID_CATEGORIES:
            category = "Autre"

        return InvoiceData(
            vendor=vendor,
            date=date_str,
            amount_ttc=amount_ttc,
            vat_amount=vat_amount,
            category=category,
            source_path=source_path,
        )

    # ── Renommage et classement ───────────────────────────────────────────────

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """
        Sanitize un nom pour l'utiliser dans un chemin de fichier.
        Supprime les caractères spéciaux et normalise les espaces.
        """
        if not name.strip():
            return "Inconnu"

        # Remplacer les accents courants
        accent_map = {
            "é": "e", "è": "e", "ê": "e", "ë": "e",
            "à": "a", "â": "a", "ä": "a",
            "ù": "u", "û": "u", "ü": "u",
            "î": "i", "ï": "i",
            "ô": "o", "ö": "o",
            "ç": "c",
        }
        result = name
        for accent, replacement in accent_map.items():
            result = result.replace(accent, replacement)
            result = result.replace(accent.upper(), replacement.upper())

        # Supprimer les caractères non alphanumériques (sauf tiret et point)
        result = re.sub(r"[^\w\s\-.]", "", result)
        # Normaliser les espaces et underscores consécutifs
        result = re.sub(r"[\s_]+", "_", result.strip())
        # Limiter la longueur
        result = result[:50]
        return result if result else "Inconnu"

    @staticmethod
    def _build_filename(data: "InvoiceData", extension: str) -> str:
        """
        Construit le nom de fichier normalisé.
        Pattern : YYYY-MM-DD_Vendor_MontantTTC.ext
        """
        date_part = data.date or "0000-00-00"
        vendor_part = AccountingAgent._sanitize_name(data.vendor or "Inconnu")
        amount_part = f"{data.amount_ttc:.2f}" if data.amount_ttc is not None else "0.00"
        ext = extension.lstrip(".")
        return f"{date_part}_{vendor_part}_{amount_part}.{ext}"

    @staticmethod
    def _build_output_path(output_folder: Path, data: "InvoiceData", filename: str) -> Path:
        """
        Construit le chemin de classement arborescent.
        Structure : /Compta/YYYY/Categorie/YYYY-MM-DD_Vendor_Montant.ext
        """
        year = data.date[:4] if data.date else "0000"
        category = AccountingAgent._sanitize_name(data.category or "Autre")
        return output_folder / "Compta" / year / category / filename

    # ── Lecture CSV bancaire ──────────────────────────────────────────────────

    @staticmethod
    def _read_csv_rows(csv_path: str) -> List[List[str]]:
        """
        Lit un CSV bancaire en détectant automatiquement le délimiteur.
        Essaie virgule, point-virgule, tabulation dans cet ordre.
        """
        for delimiter in _CSV_DELIMITERS:
            try:
                with open(csv_path, newline="", encoding="utf-8-sig") as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    rows = list(reader)
                # Valider : au moins 2 lignes et 2 colonnes
                if len(rows) >= 2 and len(rows[0]) >= 2:
                    return rows
            except Exception:
                continue
        logger.error(f"Impossible de lire le CSV : {csv_path}")
        return []

    @staticmethod
    def _detect_csv_columns(
        headers: List[str],
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """
        Détecte automatiquement les colonnes date, montant et libellé dans les en-têtes CSV.
        Retourne (date_idx, amount_idx, label_idx) — None si non détecté.
        """
        date_keywords = {"date", "jour", "day", "valeur"}
        amount_keywords = {"montant", "amount", "debit", "débit", "credit", "crédit", "solde"}
        label_keywords = {"libelle", "libellé", "label", "description", "memo", "référence", "detail"}

        date_idx: Optional[int] = None
        amount_idx: Optional[int] = None
        label_idx: Optional[int] = None

        for i, header in enumerate(headers):
            h = header.lower().strip()
            if date_idx is None and any(kw in h for kw in date_keywords):
                date_idx = i
            elif amount_idx is None and any(kw in h for kw in amount_keywords):
                amount_idx = i
            elif label_idx is None and any(kw in h for kw in label_keywords):
                label_idx = i

        return date_idx, amount_idx, label_idx

    @staticmethod
    def _parse_bank_amount(value: str) -> Optional[float]:
        """Parse un montant bancaire (gère virgule/point, négatif, symboles de devise)."""
        cleaned = value.strip().replace(" ", "").replace("\xa0", "")
        cleaned = cleaned.replace(",", ".")
        cleaned = re.sub(r"[€$£]", "", cleaned)
        try:
            return float(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _parse_bank_date(value: str) -> Optional[datetime]:
        """Parse une date bancaire dans plusieurs formats courants."""
        formats = [
            "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
            "%d/%m/%y", "%Y%m%d", "%d.%m.%Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        return None

    def _reconcile_with_bank(
        self,
        csv_path: str,
        invoices: List["InvoiceData"],
    ) -> Dict[str, Any]:
        """
        Réconcilie les factures extraites avec un export CSV bancaire.

        Pour chaque facture, cherche un débit bancaire correspondant :
        - Montant TTC match (tolérance ±0.01€)
        - Date dans une fenêtre de ±15 jours

        Retourne un rapport : N réconciliées, N orphelines, liste des orphelines.
        """
        rows = self._read_csv_rows(csv_path)
        if not rows:
            return {"reconciled": 0, "orphans": len(invoices), "orphan_list": []}

        headers = rows[0]
        date_idx, amount_idx, label_idx = self._detect_csv_columns(headers)

        if date_idx is None or amount_idx is None:
            logger.warning(f"Colonnes date/montant non détectées dans {csv_path}")
            logger.debug(f"En-têtes CSV : {headers}")
            return {"reconciled": 0, "orphans": len(invoices), "orphan_list": []}

        # Parser les lignes du relevé bancaire
        bank_rows: List[Dict[str, Any]] = []
        for row in rows[1:]:
            max_needed = max(date_idx, amount_idx)
            if len(row) <= max_needed:
                continue
            bank_date = self._parse_bank_date(row[date_idx])
            bank_amount = self._parse_bank_amount(row[amount_idx])
            bank_label = (
                row[label_idx].strip()
                if label_idx is not None and len(row) > label_idx
                else ""
            )
            if bank_date is not None and bank_amount is not None:
                bank_rows.append({
                    "date": bank_date,
                    "amount": abs(bank_amount),  # Les débits peuvent être négatifs
                    "label": bank_label,
                    "used": False,
                })

        tolerance_date = timedelta(days=15)
        # Seuil de comparaison en Decimal pour éviter les erreurs flottantes
        # (ex: 0.1 + 0.2 != 0.3 en float — critique en comptabilité)
        tolerance_amount = Decimal("0.01")

        reconciled_count = 0
        orphan_list: List[str] = []
        ambiguous_list: List[str] = []

        for invoice in invoices:
            if invoice.amount_ttc is None or invoice.date is None:
                invoice.reconciliation_status = "ORPHAN"
                orphan_list.append(
                    f"{invoice.vendor or 'Inconnu'} — montant ou date manquant"
                )
                continue

            try:
                invoice_date = datetime.strptime(invoice.date, "%Y-%m-%d")
            except ValueError:
                invoice.reconciliation_status = "ORPHAN"
                orphan_list.append(f"{invoice.vendor or 'Inconnu'} — date invalide")
                continue

            # Convertir en Decimal via str() pour éviter les erreurs de représentation
            # (ex: 0.1 + 0.2 = 0.30000000000000004 en float — fatal en compta)
            # On utilise str() pour obtenir la représentation décimale exacte
            ttc = invoice.amount_ttc
            if ttc is None:
                # Guard Optional[float] pour mypy strict — déjà vérifié ci-dessus
                invoice.reconciliation_status = "ORPHAN"
                orphan_list.append(f"{invoice.vendor or 'Inconnu'} — montant manquant")
                continue
            invoice_dec: Decimal = Decimal(str(ttc))

            # Trouver TOUS les candidats (pas seulement le premier)
            candidates = []
            for bank_row in bank_rows:
                if bank_row["used"]:
                    continue

                # Correspondance montant avec précision Decimal (±0.01€)
                row_amount_dec: Decimal = Decimal(str(bank_row["amount"]))
                if abs(row_amount_dec - invoice_dec) > tolerance_amount:
                    continue

                # Correspondance date (±15 jours)
                if abs(bank_row["date"] - invoice_date) > tolerance_date:
                    continue

                candidates.append(bank_row)

            if len(candidates) > 1:
                # Ambiguïté : plusieurs lignes bancaires correspondent
                # → le comptable doit trancher manuellement
                invoice.reconciliation_status = "AMBIGUOUS"
                labels = ", ".join(str(c["label"]) for c in candidates)
                ambiguous_list.append(
                    f"{invoice.vendor or 'Inconnu'} — "
                    f"{invoice.amount_ttc}€ le {invoice.date} "
                    f"({len(candidates)} candidats : {labels})"
                )
                logger.warning(
                    f"Ambiguïté réconciliation : {invoice.vendor} "
                    f"{invoice.amount_ttc}€ → {len(candidates)} candidats"
                )
            elif len(candidates) == 1:
                candidates[0]["used"] = True
                invoice.reconciliation_status = "RECONCILED"
                reconciled_count += 1
                logger.debug(
                    f"Facture réconciliée : {invoice.vendor} "
                    f"{invoice.amount_ttc}€ ↔ {candidates[0]['label']}"
                )
            else:
                invoice.reconciliation_status = "ORPHAN"
                orphan_list.append(
                    f"{invoice.vendor or 'Inconnu'} — "
                    f"{invoice.amount_ttc}€ le {invoice.date}"
                )

        return {
            "reconciled": reconciled_count,
            "orphans": len(orphan_list),
            "orphan_list": orphan_list,
            "ambiguous": len(ambiguous_list),
            "ambiguous_list": ambiguous_list,
        }

    # ── Rapport Markdown ──────────────────────────────────────────────────────

    @staticmethod
    def _generate_report(
        invoices: List["InvoiceData"],
        total_files: int,
        elapsed: float,
        reconciliation: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Génère le rapport Markdown final du traitement comptable."""
        success_count = sum(1 for inv in invoices if inv.amount_ttc is not None)
        failed_count = total_files - len(invoices)

        lines = [
            "# Rapport de traitement comptable",
            "",
            "> ⚠️ Traitement 100% local — aucune donnée envoyée sur internet",
            "",
            "## Résumé",
            "",
            f"- **Fichiers analysés** : {total_files}",
            f"- **Extractions réussies** : {success_count}",
            f"- **Extractions échouées** : {failed_count + (len(invoices) - success_count)}",
            f"- **Temps de traitement** : {elapsed:.1f}s",
            "",
        ]

        if reconciliation:
            lines += [
                "## Réconciliation bancaire",
                "",
                f"- **Réconciliées** : {reconciliation['reconciled']}",
                f"- **Orphelines** : {reconciliation['orphans']}",
                f"- **Ambiguës** : {reconciliation.get('ambiguous', 0)}",
            ]
            orphan_list: List[str] = reconciliation.get("orphan_list", [])
            if orphan_list:
                lines.append("")
                lines.append("### Factures orphelines")
                for orphan in orphan_list:
                    lines.append(f"  - {orphan}")
            ambiguous_list: List[str] = reconciliation.get("ambiguous_list", [])
            if ambiguous_list:
                lines.append("")
                lines.append("### ⚠️ Factures ambiguës — action manuelle requise")
                for ambiguous in ambiguous_list:
                    lines.append(f"  - {ambiguous}")
            lines.append("")

        lines += [
            "## Détail des factures",
            "",
            "| Fournisseur | Date | Montant TTC | TVA | Catégorie | Statut |",
            "|-------------|------|-------------|-----|-----------|--------|",
        ]

        for inv in invoices:
            vendor = inv.vendor or "—"
            date = inv.date or "—"
            amount = f"{inv.amount_ttc:.2f}€" if inv.amount_ttc is not None else "—"
            vat = f"{inv.vat_amount:.2f}€" if inv.vat_amount is not None else "—"
            category = inv.category or "—"
            status = inv.reconciliation_status
            lines.append(f"| {vendor} | {date} | {amount} | {vat} | {category} | {status} |")

        return "\n".join(lines)

    # ── Traitement d'un fichier individuel ────────────────────────────────────

    async def _process_single_file(
        self, file: Path, output_folder: Path
    ) -> Optional["InvoiceData"]:
        """Traite un fichier unique : extraction → LLM → renommage → classement."""
        logger.debug(f"Traitement : {file.name}")

        # Extraction du texte (opération bloquante, dans un thread)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, self._extract_text, file)

        if not text.strip():
            logger.warning(f"Texte vide pour {file.name} — fichier ignoré")
            return None

        # Extraction JSON via LLM
        prompt = self._build_extraction_prompt(text)
        raw_response = await self.ask_llm_async(
            prompt=prompt,
            model_role=self.model_role,
            temperature=0.1,
            max_tokens=200,
        )

        parsed = self._parse_invoice_json(raw_response)
        if parsed is None:
            logger.warning(f"Extraction LLM échouée pour {file.name}")
            return None

        invoice = self._normalize_invoice_data(parsed, str(file))

        # Renommage et classement dans l'arborescence cible
        filename = self._build_filename(invoice, file.suffix)
        dest_path = self._build_output_path(output_folder, invoice, filename)

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(file), str(dest_path))
            invoice.output_path = str(dest_path)
            logger.info(
                f"📁 Classé : {file.name} → {dest_path.relative_to(output_folder)}"
            )
        except Exception as e:
            logger.error(f"Erreur classement {file.name} : {e}")

        return invoice

    # ── Implémentation des tools ──────────────────────────────────────────────

    async def _tool_extract_invoice(self, file_path: str) -> str:
        """Extrait les données structurées d'une facture individuelle."""
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return json.dumps({"error": f"Fichier non trouvé : {file_path}"})

        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, self._extract_text, path)

        if not text.strip():
            return json.dumps({"error": "Texte non extractible", "file": file_path})

        prompt = self._build_extraction_prompt(text)
        raw_response = await self.ask_llm_async(
            prompt=prompt,
            model_role=self.model_role,
            temperature=0.1,
            max_tokens=200,
        )

        parsed = self._parse_invoice_json(raw_response)
        if parsed is None:
            return json.dumps({"error": "JSON non parseable", "raw": raw_response[:200]})

        invoice = self._normalize_invoice_data(parsed, file_path)
        return json.dumps(invoice.to_dict(), ensure_ascii=False)

    async def _tool_reconcile(self, csv_path: str, invoices_json: str) -> str:
        """Réconcilie un lot de factures avec un export CSV bancaire."""
        try:
            raw_list: List[Dict[str, Any]] = json.loads(invoices_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"JSON invalide : {e}"})

        invoices = [
            InvoiceData(
                vendor=inv.get("vendor"),
                date=inv.get("date"),
                amount_ttc=(
                    float(inv["amount_ttc"])
                    if inv.get("amount_ttc") is not None
                    else None
                ),
                vat_amount=(
                    float(inv["vat_amount"])
                    if inv.get("vat_amount") is not None
                    else None
                ),
                category=str(inv.get("category", "Autre")),
                source_path=str(inv.get("source_path", "")),
            )
            for inv in raw_list
        ]

        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(
            None, self._reconcile_with_bank, csv_path, invoices
        )
        return json.dumps(report, ensure_ascii=False)

    async def _tool_process_batch(
        self,
        input_folder: str,
        output_folder: str,
        bank_csv: Optional[str] = None,
    ) -> str:
        """
        Traite un lot de factures : extraction, renommage, classement et réconciliation.

        Processus :
        1. Scanner input_folder pour tous les PDF/DOCX/images
        2. Pour chaque fichier : extraire texte → LLM → JSON → renommer → classer
        3. Si bank_csv fourni : réconciliation bancaire
        4. Générer un rapport Markdown
        """
        start_time = time.time()
        input_path = Path(input_folder).expanduser().resolve()
        output_path = Path(output_folder).expanduser().resolve()

        if not input_path.exists():
            return f"Dossier source introuvable : {input_folder}"
        if not input_path.is_dir():
            return f"Le chemin source n'est pas un dossier : {input_folder}"

        # Scanner les fichiers supportés
        files = [
            f for f in input_path.iterdir()
            if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTENSIONS
        ]

        if not files:
            return f"Aucun fichier supporté trouvé dans {input_folder}"

        logger.info(f"🧾 Traitement de {len(files)} factures depuis {input_folder}")
        output_path.mkdir(parents=True, exist_ok=True)

        # Traitement concurrent avec Semaphore
        async def process_file(file: Path) -> Optional[InvoiceData]:
            async with self._semaphore:
                return await self._process_single_file(file, output_path)

        tasks = [process_file(f) for f in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        invoices: List[InvoiceData] = []
        for result in results:
            if isinstance(result, InvoiceData):
                invoices.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Erreur traitement fichier : {result}")

        # Réconciliation bancaire (optionnelle)
        reconciliation: Optional[Dict[str, Any]] = None
        if bank_csv:
            bank_path = Path(bank_csv).expanduser().resolve()
            if bank_path.exists():
                logger.info(f"📊 Réconciliation avec {bank_csv}")
                loop = asyncio.get_running_loop()
                reconciliation = await loop.run_in_executor(
                    None, self._reconcile_with_bank, str(bank_path), invoices
                )
            else:
                logger.warning(f"Fichier CSV bancaire introuvable : {bank_csv}")

        elapsed = time.time() - start_time
        report = self._generate_report(invoices, len(files), elapsed, reconciliation)

        # Sauvegarder le rapport dans le dossier de sortie
        report_path = output_path / "rapport_comptable.md"
        try:
            report_path.write_text(report, encoding="utf-8")
            logger.info(f"📋 Rapport sauvegardé : {report_path}")
        except Exception as e:
            logger.error(f"Erreur sauvegarde rapport : {e}")

        logger.info(
            f"✅ Traitement terminé : {len(invoices)}/{len(files)} factures "
            f"traitées en {elapsed:.1f}s"
        )
        logger.info("🔒 Traitement 100% local — aucune donnée envoyée sur internet")

        return report

    # ── handle() — langage naturel ────────────────────────────────────────────

    async def handle(self, query: str) -> str:
        """Traite une requête comptable en langage naturel."""
        prompt = (
            f'Tu es l\'AccountingAgent, assistant comptable expert.\n'
            f'Requête : "{query}"\n\n'
            "Si la requête contient un chemin de dossier source, génère :\n"
            '{"action": "process_batch", "input_folder": "...", "output_folder": "..."}\n'
            'Sinon : {"action": "explain"}\n'
            "Réponds UNIQUEMENT avec ce JSON."
        )

        try:
            response = self.ask_llm(prompt, model_role=self.model_role, temperature=0.1)
            parsed = self._parse_invoice_json(response)

            if parsed and parsed.get("action") == "process_batch":
                input_folder = str(parsed.get("input_folder", ""))
                output_folder = str(parsed.get("output_folder", "~/Compta"))
                raw_csv = parsed.get("bank_csv")
                return await self._tool_process_batch(
                    input_folder=input_folder,
                    output_folder=output_folder,
                    bank_csv=str(raw_csv) if raw_csv else None,
                )
        except Exception as e:
            logger.error(f"Erreur AccountingAgent.handle : {e}")

        return (
            "Je suis l'AccountingAgent. Je peux :\n"
            "- Traiter un lot de factures (PDF, Word, images)\n"
            "- Extraire automatiquement : fournisseur, date, montant TTC, TVA, catégorie\n"
            "- Renommer et classer les fichiers automatiquement\n"
            "- Réconcilier avec votre relevé bancaire CSV\n"
            "- Générer un rapport Markdown\n\n"
            "🔒 Traitement 100% local — aucune donnée envoyée sur internet\n\n"
            "Exemple : 'Traite les factures dans ~/Desktop/Factures "
            "et classe-les dans ~/Compta'"
        )
