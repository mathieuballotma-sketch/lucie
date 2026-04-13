"""
DossierAnalyzer — analyse de dossiers complets (jusqu'à 50 fichiers).

Pipeline par lots :
  1. Scan du dossier → extraction texte de chaque fichier
  2. Découpage en chunks (~2000 tokens max)
  3. Pour chaque chunk : extraction juridique via Lecteur + cross-ref Retriever
  4. Accumulation des résultats intermédiaires (persistés sur disque)
  5. Synthèse finale via Rédacteur + Vérification

Aucune dépendance au reste du repo.
"""

import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ollama_client, retriever
from .config import (
    DOSSIER_LECTEUR_PARAMS,
    DOSSIER_SYNTHESE_PARAMS,
    DOSSIER_TIMEOUT,
    MAX_CHUNK_TOKENS,
    MAX_FILES_PER_DOSSIER,
    VERIFICATEUR_PARAMS,
)

_LECTEUR_PROMPT_PATH = Path(__file__).parent / "prompts" / "dossier_lecteur_system.txt"
_SYNTHESE_PROMPT_PATH = Path(__file__).parent / "prompts" / "dossier_synthese_system.txt"

# Extensions supportées
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


# ─── Structures de données ───────────────────────────────────────────────────

@dataclass
class ChunkInfo:
    text: str
    source_file: str
    chunk_index: int
    total_chunks: int


@dataclass
class JuridicalPoint:
    article: str
    texte_loi: str
    contexte_dossier: str
    fichier_source: str
    pertinence: str
    gravite: str = "important"


@dataclass
class DossierReport:
    references_juridiques: List[JuridicalPoint] = field(default_factory=list)
    synthese_globale: str = ""
    fichiers_analyses: List[str] = field(default_factory=list)
    nb_chunks_traites: int = 0
    erreurs: List[str] = field(default_factory=list)
    duree_secondes: float = 0.0


# ─── Extraction de texte ─────────────────────────────────────────────────────

def _extract_text_pdf(path: Path) -> str:
    """Extrait le texte d'un PDF via pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber requis pour lire les PDF. "
            "Installer : pip install pdfplumber"
        )
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def _extract_text_docx(path: Path) -> str:
    """Extrait le texte d'un fichier Word (.docx)."""
    try:
        import docx
    except ImportError:
        raise ImportError(
            "python-docx requis pour lire les fichiers Word. "
            "Installer : pip install python-docx"
        )
    doc = docx.Document(str(path))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_text_plain(path: Path) -> str:
    """Lit un fichier texte brut (.txt, .md)."""
    return path.read_text(encoding="utf-8")


def extract_text(path: Path) -> str:
    """Extrait le texte d'un fichier selon son extension."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_text_pdf(path)
    elif ext == ".docx":
        return _extract_text_docx(path)
    elif ext in (".txt", ".md"):
        return _extract_text_plain(path)
    else:
        raise ValueError(f"Extension non supportée : {ext}")


# ─── Découpage en chunks ─────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Estimation grossière : ~1 token par 4 caractères en français."""
    return len(text) // 4


def _split_into_sentences(text: str) -> List[str]:
    """Découpe un texte en phrases (ne coupe jamais au milieu d'une phrase)."""
    sentences = re.split(r'(?<=[.!?;])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


def chunk_text(text: str, source_file: str, max_tokens: int = MAX_CHUNK_TOKENS) -> List[ChunkInfo]:
    """
    Découpe un texte en chunks de max_tokens.
    Ne coupe jamais au milieu d'une phrase.
    """
    if _estimate_tokens(text) <= max_tokens:
        return [ChunkInfo(text=text, source_file=source_file, chunk_index=0, total_chunks=1)]

    sentences = _split_into_sentences(text)
    chunks: List[ChunkInfo] = []
    current_chunk: List[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = _estimate_tokens(sentence)

        # Si une seule phrase dépasse le max, on la garde quand même
        if sentence_tokens > max_tokens and not current_chunk:
            chunks.append(ChunkInfo(
                text=sentence,
                source_file=source_file,
                chunk_index=len(chunks),
                total_chunks=0,  # sera mis à jour après
            ))
            continue

        if current_tokens + sentence_tokens > max_tokens and current_chunk:
            chunks.append(ChunkInfo(
                text=" ".join(current_chunk),
                source_file=source_file,
                chunk_index=len(chunks),
                total_chunks=0,
            ))
            current_chunk = []
            current_tokens = 0

        current_chunk.append(sentence)
        current_tokens += sentence_tokens

    if current_chunk:
        chunks.append(ChunkInfo(
            text=" ".join(current_chunk),
            source_file=source_file,
            chunk_index=len(chunks),
            total_chunks=0,
        ))

    # Mise à jour du total
    for c in chunks:
        c.total_chunks = len(chunks)

    return chunks


# ─── Scan du dossier ─────────────────────────────────────────────────────────

def scan_dossier(folder_path: str) -> List[Path]:
    """Liste tous les fichiers supportés dans le dossier (non-récursif puis récursif)."""
    folder = Path(folder_path)
    if not folder.is_dir():
        raise FileNotFoundError(f"Dossier introuvable : {folder_path}")

    files = sorted(
        f for f in folder.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if len(files) > MAX_FILES_PER_DOSSIER:
        raise ValueError(
            f"Trop de fichiers ({len(files)}). "
            f"Maximum : {MAX_FILES_PER_DOSSIER}. "
            "Réduisez le dossier ou augmentez MAX_FILES_PER_DOSSIER."
        )

    return files


# ─── Analyse d'un chunk via LLM ─────────────────────────────────────────────

async def _analyze_chunk(chunk: ChunkInfo, verbose: bool = False) -> Dict[str, Any]:
    """Analyse un chunk et extrait les points juridiques."""
    system = _LECTEUR_PROMPT_PATH.read_text(encoding="utf-8")

    prompt = (
        f"Fichier source : {chunk.source_file} "
        f"(extrait {chunk.chunk_index + 1}/{chunk.total_chunks})\n\n"
        "Extrais tous les points juridiques de cet extrait. "
        "Réponds UNIQUEMENT avec le JSON valide.\n\n"
        f"---\n{chunk.text}\n---"
    )

    options = {k: v for k, v in DOSSIER_LECTEUR_PARAMS.items() if k != "model"}

    response = await ollama_client.generate(
        model=DOSSIER_LECTEUR_PARAMS["model"],
        prompt=prompt,
        system=system,
        options=options,
    )

    parsed = ollama_client.extract_json_from_response(response)
    if parsed is None:
        # Retry une fois
        response = await ollama_client.generate(
            model=DOSSIER_LECTEUR_PARAMS["model"],
            prompt=prompt + "\n\nIMPORTANT : JSON valide uniquement, sans markdown.",
            system=system,
            options=options,
        )
        parsed = ollama_client.extract_json_from_response(response)

    if parsed is None:
        return {"points_juridiques": [], "resume": "Extraction échouée", "erreur": True}

    return parsed


# ─── Cross-référence avec la base curatée ────────────────────────────────────

async def _crossref_with_knowledge(points: List[Dict[str, Any]]) -> List[JuridicalPoint]:
    """Pour chaque point juridique, cherche les articles exacts dans la base curatée."""
    results: List[JuridicalPoint] = []

    for point in points:
        articles = point.get("articles_potentiels", [])
        phrase = point.get("phrase_document", "")
        description = point.get("description", "")
        fichier = point.get("fichier_source", "inconnu")
        gravite = point.get("gravite", "important")

        # Chercher dans la base curatée via le Retriever
        search_query = json.dumps({
            "mentions_legales": articles,
            "contexte": description,
        }, ensure_ascii=False)

        sources_json = await retriever.handle(search_query)

        try:
            sources_data = json.loads(sources_json)
            all_sources = (
                sources_data.get("sources", [])
                + sources_data.get("jurisprudences", [])
            )
        except json.JSONDecodeError:
            all_sources = []

        if all_sources:
            for source in all_sources:
                results.append(JuridicalPoint(
                    article=source.get("id", ""),
                    texte_loi=source.get("extrait", ""),
                    contexte_dossier=phrase,
                    fichier_source=fichier,
                    pertinence=description,
                    gravite=gravite,
                ))
        elif articles:
            # Pas trouvé dans la base, mais on garde la référence potentielle
            for art in articles:
                results.append(JuridicalPoint(
                    article=art,
                    texte_loi="(Non trouvé dans la base curatée)",
                    contexte_dossier=phrase,
                    fichier_source=fichier,
                    pertinence=description,
                    gravite=gravite,
                ))

    return results


# ─── Persistance des résultats intermédiaires ────────────────────────────────

def _save_intermediate(results: List[JuridicalPoint], tmp_dir: Path, batch_num: int) -> Path:
    """Sauvegarde les résultats intermédiaires sur disque."""
    data = [
        {
            "article": r.article,
            "texte_loi": r.texte_loi,
            "contexte_dossier": r.contexte_dossier,
            "fichier_source": r.fichier_source,
            "pertinence": r.pertinence,
            "gravite": r.gravite,
        }
        for r in results
    ]
    path = tmp_dir / f"batch_{batch_num:03d}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_all_intermediate(tmp_dir: Path) -> List[Dict[str, Any]]:
    """Charge tous les résultats intermédiaires."""
    all_results: List[Dict[str, Any]] = []
    for path in sorted(tmp_dir.glob("batch_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        all_results.extend(data)
    return all_results


# ─── Déduplication des références ────────────────────────────────────────────

def _deduplicate_references(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Déduplique les références juridiques par article + contexte."""
    seen = set()
    unique: List[Dict[str, Any]] = []
    for ref in refs:
        key = (ref.get("article", ""), ref.get("contexte_dossier", "")[:100])
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return unique


# ─── Synthèse finale ─────────────────────────────────────────────────────────

async def _generate_synthese(
    all_refs: List[Dict[str, Any]],
    fichiers: List[str],
    instruction: str,
    verbose: bool = False,
) -> str:
    """Génère la synthèse globale à partir de toutes les découvertes."""
    system = _SYNTHESE_PROMPT_PATH.read_text(encoding="utf-8")

    # Tronquer si trop de références pour le contexte
    refs_json = json.dumps(all_refs[:50], ensure_ascii=False, indent=2)

    prompt = (
        f"## Instruction de l'utilisateur\n\n{instruction}\n\n"
        f"## Fichiers analysés ({len(fichiers)})\n\n"
        + "\n".join(f"- {f}" for f in fichiers)
        + "\n\n"
        f"## Découvertes juridiques ({len(all_refs)} points identifiés)\n\n"
        f"```json\n{refs_json}\n```\n\n"
        "Produis maintenant la synthèse complète selon la structure demandée."
    )

    options = {k: v for k, v in DOSSIER_SYNTHESE_PARAMS.items() if k != "model"}

    return await ollama_client.generate(
        model=DOSSIER_SYNTHESE_PARAMS["model"],
        prompt=prompt,
        system=system,
        options=options,
    )


# ─── Point d'entrée principal ────────────────────────────────────────────────

async def analyze_dossier(
    folder_path: str,
    instruction: str = "Analyse juridique complète du dossier",
    verbose: bool = False,
) -> DossierReport:
    """
    Analyse un dossier complet de documents juridiques.

    Args:
        folder_path: Chemin vers le dossier contenant les fichiers.
        instruction: Instruction/question de l'utilisateur.
        verbose: Affiche la progression.

    Returns:
        DossierReport avec toutes les découvertes et la synthèse.
    """
    start = time.time()
    report = DossierReport()

    # ── 1. Scan du dossier ───────────────────────────────────────────────────
    if verbose:
        print(f"📁 Scan du dossier : {folder_path}", flush=True)

    try:
        files = scan_dossier(folder_path)
    except (FileNotFoundError, ValueError) as e:
        report.erreurs.append(str(e))
        return report

    if not files:
        report.erreurs.append("Aucun fichier supporté trouvé dans le dossier.")
        return report

    report.fichiers_analyses = [f.name for f in files]
    if verbose:
        print(f"📄 {len(files)} fichier(s) trouvé(s)", flush=True)

    # ── 2. Extraction texte + découpage en chunks ────────────────────────────
    all_chunks: List[ChunkInfo] = []
    for f in files:
        try:
            text = extract_text(f)
            if not text.strip():
                report.erreurs.append(f"Fichier vide : {f.name}")
                continue
            chunks = chunk_text(text, f.name)
            all_chunks.extend(chunks)
            if verbose:
                print(f"  ✂️  {f.name} → {len(chunks)} chunk(s)", flush=True)
        except Exception as e:
            report.erreurs.append(f"Erreur lecture {f.name} : {e}")
            if verbose:
                print(f"  ❌ {f.name} : {e}", flush=True)

    if not all_chunks:
        report.erreurs.append("Aucun texte extractible dans le dossier.")
        return report

    if verbose:
        print(f"\n🔄 {len(all_chunks)} chunk(s) à analyser…\n", flush=True)

    # ── 3. Analyse par lots (persistance intermédiaire) ──────────────────────
    tmp_dir = Path(tempfile.mkdtemp(prefix="lucie_dossier_"))
    batch_num = 0

    for i, chunk in enumerate(all_chunks):
        elapsed = time.time() - start
        if elapsed > DOSSIER_TIMEOUT:
            report.erreurs.append(
                f"Timeout ({DOSSIER_TIMEOUT:.0f}s) atteint après {i} chunks."
            )
            break

        if verbose:
            print(
                f"  [{i + 1}/{len(all_chunks)}] {chunk.source_file} "
                f"(chunk {chunk.chunk_index + 1}/{chunk.total_chunks})…",
                flush=True,
            )

        # Extraction des points juridiques
        chunk_result = await _analyze_chunk(chunk, verbose)
        points = chunk_result.get("points_juridiques", [])

        # Ajouter le fichier source à chaque point
        for p in points:
            p["fichier_source"] = chunk.source_file

        if points:
            # Cross-référence avec la base curatée
            refs = await _crossref_with_knowledge(points)
            report.references_juridiques.extend(refs)
            _save_intermediate(refs, tmp_dir, batch_num)
            batch_num += 1

            if verbose:
                print(f"    → {len(points)} point(s) juridique(s) trouvé(s)", flush=True)
        else:
            if verbose:
                print("    → aucun point juridique", flush=True)

        report.nb_chunks_traites += 1

    # ── 4. Charger et dédupliquer tous les résultats ─────────────────────────
    all_refs = _load_all_intermediate(tmp_dir)
    all_refs = _deduplicate_references(all_refs)

    if verbose:
        print(
            f"\n📊 Total : {len(all_refs)} référence(s) juridique(s) unique(s)\n",
            flush=True,
        )

    # Reconstruire les JuridicalPoint dédupliqués
    report.references_juridiques = [
        JuridicalPoint(**ref) for ref in all_refs
    ]

    # ── 5. Synthèse finale ───────────────────────────────────────────────────
    if all_refs:
        if verbose:
            print("✍️  Synthèse finale en cours…", flush=True)

        report.synthese_globale = await _generate_synthese(
            all_refs,
            report.fichiers_analyses,
            instruction,
            verbose,
        )

        if verbose:
            print("✅ Synthèse terminée", flush=True)
    else:
        report.synthese_globale = (
            "Aucune référence juridique identifiée dans le dossier. "
            "Le dossier ne contient peut-être pas de documents juridiques "
            "pertinents, ou les documents n'ont pas pu être analysés correctement."
        )

    report.duree_secondes = time.time() - start

    # Nettoyage du répertoire temporaire
    try:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

    return report


# ─── Formatage du rapport ────────────────────────────────────────────────────

def format_report(report: DossierReport) -> str:
    """Formate un DossierReport en texte Markdown lisible."""
    parts: List[str] = []

    # Entête
    parts.append("# Rapport d'analyse de dossier — Lucie V1\n")
    parts.append(
        f"- **Fichiers analysés** : {len(report.fichiers_analyses)}\n"
        f"- **Chunks traités** : {report.nb_chunks_traites}\n"
        f"- **Références juridiques** : {len(report.references_juridiques)}\n"
        f"- **Durée** : {report.duree_secondes:.1f}s\n"
    )

    # Erreurs
    if report.erreurs:
        parts.append("## Avertissements\n")
        for err in report.erreurs:
            parts.append(f"- {err}")
        parts.append("")

    # Synthèse
    if report.synthese_globale:
        parts.append("---\n")
        parts.append(report.synthese_globale)
        parts.append("")

    # Tableau des références
    if report.references_juridiques:
        parts.append("\n## Détail des références juridiques\n")
        for i, ref in enumerate(report.references_juridiques, 1):
            parts.append(f"### {i}. {ref.article}\n")
            parts.append(f"- **Gravité** : {ref.gravite}")
            parts.append(f"- **Source** : {ref.fichier_source}")
            parts.append(f"- **Texte de loi** : {ref.texte_loi[:300]}")
            parts.append(f"- **Contexte dossier** : {ref.contexte_dossier[:300]}")
            parts.append(f"- **Pertinence** : {ref.pertinence}")
            parts.append("")

    # Disclaimer
    parts.append(
        "\n---\n"
        f"_Rapport généré par Lucie V1 — Analyse de dossier — "
        f"{report.duree_secondes:.1f}s_\n"
        "_À vérifier par un avocat qualifié avant tout usage professionnel._"
    )

    return "\n".join(parts)
