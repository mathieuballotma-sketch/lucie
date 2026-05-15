"""Fixtures programmatiques pour le document_analyzer.

Génération à l'exécution des 5 dossiers fictifs via reportlab (PDF) +
python-docx (docx). Aucun binaire commité. Tous les noms/sociétés sont
inventés (truth rule : pas de données client réelles dans les tests).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# ─── Contenus des 5 fixtures (texte fictif lisible dans le code) ──────────────

FIXTURE_LIC_ECO_CADRE_PAGES: tuple[str, ...] = (
    # Page 1 — contexte
    "Dossier de licenciement économique — M. Jean Dupont, cadre commercial.\n"
    "Société X SAS, secteur logistique. Effectif : 240 salariés.\n"
    "Motif invoqué : suppression de poste pour cessation d'activité de la "
    "branche logistique régionale. Procédure de licenciement collectif "
    "déclenchée le 15 mars 2026 — moins de 10 salariés concernés sur 30 jours.",
    # Page 2 — pièces produites
    "Pièces communiquées par le salarié :\n"
    "- Lettre de licenciement du 28 mars 2026 motivant la suppression de poste\n"
    "- Convention collective applicable : transport et logistique\n"
    "- Préavis de 3 mois — contrat de travail CDI signé en 2018\n"
    "- Critères d'ordre des licenciements appliqués : charges familiales, "
    "ancienneté, qualités professionnelles.",
    # Page 3 — demande
    "Demande de M. Dupont : vérifier la régularité du motif économique, "
    "le respect du contrat de sécurisation professionnelle (CSP), et le "
    "calcul de l'indemnité de licenciement. Saisine du conseil de "
    "prud'hommes envisagée si motif jugé non sérieux.",
)

FIXTURE_LIC_PERSO_FAUTE: tuple[str, ...] = (
    "Dossier de licenciement pour faute grave — M. Paul Martin, technicien.",
    "Société Y SARL, secteur BTP. CDI signé en 2020. Salarié protégé : non.",
    "Faits reprochés : absences injustifiées répétées en mars 2026 (12 jours "
    "consécutifs), non-respect de la convention collective du bâtiment.",
    "Lettre de convocation à entretien préalable du 5 avril 2026.",
    "Licenciement prononcé le 18 avril 2026 — préavis non exécuté, dispense "
    "de préavis pour faute grave. Indemnité de licenciement refusée.",
    "Demande du salarié : contestation devant le conseil de prud'hommes — "
    "qualification de la faute, demande de requalification en cause réelle "
    "et sérieuse. Convention collective applicable invoquée. Démission non "
    "envisagée. Employeur a-t-il respecté le délai d'envoi ?",
    "Mention : aucun PSE en cours, effectif < 11 salariés.",
)

FIXTURE_SOCIETE_SARL_PAGES: tuple[str, ...] = (
    "Cession de parts SARL — Société Z. Capital social : 100 000 EUR. "
    "Gérant : M. Pierre Bernard. Assemblée générale du 12 mai 2026.",
    "Cession actions par cession parts entre associés. Statuts modifiés. "
    "Conseil administration consulté. Président SAS : non applicable, "
    "SARL régime gérance.",
    "Demande : rédaction d'un acte de cession parts, mise à jour des statuts "
    "et formalités RCS. SAS et SA non concernées.",
)

FIXTURE_PHARMA_PUB_PAGES: tuple[str, ...] = (
    "Dossier publicité médicament — Laboratoire A, produit antalgique "
    "paracétamol 500 mg.",
    "Demande : conformité à la réglementation ANSM sur la publicité grand "
    "public et auprès des professionnels de santé. Visa PM exigé.",
    "Pièces : maquette télévisuelle, script radio, brochures pharmaciens. "
    "Charte HAS et code de la santé publique cités. Aucune mention "
    "d'effets secondaires graves dans la maquette TV.",
    "Risque réglementaire : sanction ANSM, retrait de visa, rappel produit. "
    "Pharmacovigilance et bonnes pratiques cliniques à respecter.",
)

FIXTURE_MIXTE_LIC_FISCAL_PARAGRAPHS: tuple[str, ...] = (
    # Première moitié : licenciement économique (in-scope)
    "Dossier mixte — Mme Claire Bernard, directrice administrative.",
    "Société W SAS, secteur retail. Licenciement économique notifié le "
    "10 mai 2026. Motif : suppression de poste consécutive à fermeture site.",
    "Convention collective du commerce de détail applicable. CDI 12 ans "
    "d'ancienneté. Préavis 3 mois. Contrat de sécurisation professionnelle "
    "(CSP) proposé. Plan de sauvegarde de l'emploi (PSE) en cours sur le "
    "périmètre national : 35 salariés concernés sur 30 jours.",
    "Critères d'ordre des licenciements : charges familiales (3 enfants), "
    "ancienneté élevée, qualités professionnelles certifiées.",
    "Saisine prud'hommes envisagée — contestation du motif économique.",
    # Seconde moitié : calcul indemnité fiscal (out-of-scope partiel)
    "Question fiscale annexe — fiscalité de l'indemnité de licenciement.",
    "Calcul de l'impôt sur le revenu (IR) sur l'indemnité supra-légale. "
    "Quelle imposition s'applique ? Quelle exonération possible au regard "
    "du CGI ? Crédit d'impôt envisageable ? Déclaration de revenus 2027 "
    "à anticiper. Conseil fiscaliste demandé pour optimisation.",
    "Régime de TVA non applicable (indemnité non soumise). Mention impôt "
    "sociétés (IS) : non concerné, salariée non dirigeante.",
)


def _write_pdf(path: Path, pages: Iterable[str]) -> None:
    """Écrit un PDF multi-pages avec un wrap simple. reportlab uniquement."""
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    for page_text in pages:
        text_object = c.beginText(50, height - 60)
        text_object.setFont("Helvetica", 11)
        for line in page_text.split("\n"):
            # wrap basique à ~95 chars pour rester dans la largeur A4
            while len(line) > 95:
                cut = line.rfind(" ", 0, 95)
                if cut <= 0:
                    cut = 95
                text_object.textLine(line[:cut])
                line = line[cut:].lstrip()
            text_object.textLine(line)
        c.drawText(text_object)
        c.showPage()
    c.save()


def _write_docx(path: Path, paragraphs: Iterable[str]) -> None:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(str(path))


# ─── Fixtures pytest ───────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("doc_analyzer_fixtures")


@pytest.fixture(scope="session")
def fixture_lic_eco_pdf(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "dossier_licenciement_eco_cadre.pdf"
    _write_pdf(path, FIXTURE_LIC_ECO_CADRE_PAGES)
    return path


@pytest.fixture(scope="session")
def fixture_lic_perso_docx(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "dossier_licenciement_perso_faute.docx"
    _write_docx(path, FIXTURE_LIC_PERSO_FAUTE)
    return path


@pytest.fixture(scope="session")
def fixture_societe_sarl_pdf(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "dossier_societe_SARL.pdf"
    _write_pdf(path, FIXTURE_SOCIETE_SARL_PAGES)
    return path


@pytest.fixture(scope="session")
def fixture_pharma_pdf(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "dossier_pharma_pub.pdf"
    _write_pdf(path, FIXTURE_PHARMA_PUB_PAGES)
    return path


@pytest.fixture(scope="session")
def fixture_mixte_docx(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "dossier_mixte_lic_eco_fiscal.docx"
    _write_docx(path, FIXTURE_MIXTE_LIC_FISCAL_PARAGRAPHS)
    return path


@pytest.fixture(scope="session")
def fixture_empty_pdf(fixtures_dir: Path) -> Path:
    """PDF avec 0 page — pour test EmptyDocumentError. reportlab ne sait pas
    créer un PDF sans page ; on construit le PDF minimaliste à la main."""
    path = fixtures_dir / "empty.pdf"
    # PDF 1.4 minimal avec un /Pages /Count 0 — pdfplumber l'ouvrira proprement
    # et reportera 0 page.
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Count 0 /Kids [] >> endobj\n"
        b"xref\n0 3\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"trailer << /Size 3 /Root 1 0 R >>\n"
        b"startxref\n108\n%%EOF\n"
    )
    return path


@pytest.fixture(scope="session")
def fixture_scan_pdf(fixtures_dir: Path) -> Path:
    """PDF de 1 page contenant seulement quelques caractères — simule un
    scan dont l'OCR n'a pas été fait. doit déclencher ScannedPDFError."""
    path = fixtures_dir / "scan_image.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawString(50, 800, "x")  # 1 caractère utile
    c.showPage()
    c.save()
    return path


@pytest.fixture(scope="session")
def fixture_corrupt_pdf(fixtures_dir: Path) -> Path:
    """Fichier .pdf mais contenu binaire arbitraire — déclencheur CorruptedFileError."""
    path = fixtures_dir / "corrupt.pdf"
    path.write_bytes(b"not a real pdf\x00\x01\x02\x03")
    return path


@pytest.fixture(scope="session")
def fixture_unsupported(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "dossier.txt"
    path.write_text("Texte simple", encoding="utf-8")
    return path
