"""
Parseur minimal DILA LEGI → SQLite pour Lucie.

Stratégie : stdlib uniquement (`tarfile` + `xml.etree.ElementTree`).
N'utilise PAS `vendor/legi/tar2sqlite.py` directement pour :
- éviter la dépendance native `hunspell` (requise transitivement par legi.py),
- éviter `libarchive-c` et `lxml` (non-stdlib),
- maîtriser la compat Python 3.13.

On extrait uniquement ce qui sert le retrieval :
- `articles` en état `VIGUEUR` : num, prefix, texte, dates, url_legifrance
- `codes` (métadonnées via `TEXTE_VERSION`) : cid, titre, date_maj

Les versions passées, liens, sections, sommaires, anomalies : NON extraits.
Le schéma `vendor/legi/sql/` complet reste consultable si on veut migrer
plus tard vers un usage avancé.

API publique :
- `apply_archive(tarball_path, conn)` : applique un .tar.gz sur la DB.
- `init_db(db_path)`                 : crée la DB + schéma.
- `parse_article_xml(xml_bytes)`     : extrait un `ArticleRecord` depuis XML.
- `parse_texte_version_xml(xml_bytes)` : extrait un `CodeRecord`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import tarfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

LEGIFRANCE_ARTICLE_URL = "https://www.legifrance.gouv.fr/codes/article_lc/{id}"
LEGIFRANCE_CODE_URL = "https://www.legifrance.gouv.fr/codes/id/{cid}"

_NUM_PREFIX_RE = re.compile(r"^\s*(?P<prefix>[LRDA]?)\s*\.?\s*(?P<numeric>\d+)")


@dataclass(frozen=True)
class ArticleRecord:
    id: str
    code_cid: str
    num: str
    num_prefix: str
    num_numeric: int | None
    etat: str
    date_debut: str | None
    date_fin: str | None
    texte: str
    nota: str | None
    url_legifrance: str
    mtime: int


@dataclass(frozen=True)
class CodeRecord:
    cid: str
    titre: str
    date_maj: str | None


class ParseError(RuntimeError):
    """XML mal formé ou champs requis manquants."""


def init_db(db_path: Path, schema_path: Path = SCHEMA_PATH) -> sqlite3.Connection:
    """Crée la DB + schéma si absents. Retourne une connexion ouverte."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def _text(node: ET.Element | None) -> str | None:
    """Texte direct d'un élément, ou None si nœud absent / vide."""
    if node is None:
        return None
    raw = node.text
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _inner_text(node: ET.Element | None) -> str | None:
    """
    Concatène tout le texte descendant (équivalent `.textContent` DOM),
    avec normalisation d'espaces. DILA stocke le contenu d'article sous
    forme d'HTML-ish (`<br/>`, `<p>`, etc.) dans BLOC_TEXTUEL/CONTENU —
    on aplatit pour le BM25.
    """
    if node is None:
        return None
    parts: list[str] = []
    for chunk in node.itertext():
        parts.append(chunk)
    text = " ".join(parts).strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def _parse_num_prefix(num: str) -> tuple[str, int | None]:
    """
    Extrait (prefix, numeric) depuis `num` :
        "L1233-1"  → ("L", 1233)
        "R145-2"   → ("R", 145)
        "212"      → ("", 212)
        "*"        → ("", None)
    """
    match = _NUM_PREFIX_RE.match(num)
    if match is None:
        return ("", None)
    prefix = match.group("prefix") or ""
    try:
        numeric = int(match.group("numeric"))
    except (TypeError, ValueError):
        numeric = None
    return (prefix, numeric)


def parse_article_xml(xml_bytes: bytes, mtime: int = 0) -> ArticleRecord:
    """
    Parse un XML `ARTICLE` DILA → `ArticleRecord`.

    Lève `ParseError` si la racine n'est pas ARTICLE ou si un champ requis
    est absent (ID, NUM, ETAT, contenu textuel).
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ParseError(f"XML mal formé: {exc}") from exc

    if root.tag != "ARTICLE":
        raise ParseError(f"racine attendue ARTICLE, obtenue {root.tag!r}")

    meta_commun = root.find("META/META_COMMUN")
    meta_article = root.find("META/META_SPEC/META_ARTICLE")
    if meta_commun is None or meta_article is None:
        raise ParseError("META/META_COMMUN ou META_SPEC/META_ARTICLE absent")

    article_id = _text(meta_commun.find("ID"))
    if not article_id:
        raise ParseError("META_COMMUN/ID absent")

    contexte_texte = root.find("CONTEXTE/TEXTE")
    code_cid = contexte_texte.get("cid") if contexte_texte is not None else None
    if not code_cid:
        raise ParseError(f"CONTEXTE/TEXTE@cid absent pour {article_id}")

    num = _text(meta_article.find("NUM")) or ""
    prefix, numeric = _parse_num_prefix(num)
    etat = _text(meta_article.find("ETAT")) or "INCONNU"
    date_debut = _text(meta_article.find("DATE_DEBUT"))
    date_fin = _text(meta_article.find("DATE_FIN"))

    texte = _inner_text(root.find("BLOC_TEXTUEL/CONTENU"))
    if texte is None:
        # Article sans contenu textuel (ex : purement référentiel).
        # On stocke tout de même, texte vide, pour ne pas casser le schema.
        texte = ""

    nota = _inner_text(root.find("NOTA/CONTENU"))
    url = LEGIFRANCE_ARTICLE_URL.format(id=article_id)

    return ArticleRecord(
        id=article_id,
        code_cid=code_cid,
        num=num,
        num_prefix=prefix,
        num_numeric=numeric,
        etat=etat,
        date_debut=date_debut,
        date_fin=date_fin,
        texte=texte,
        nota=nota,
        url_legifrance=url,
        mtime=mtime,
    )


def parse_texte_version_xml(xml_bytes: bytes) -> CodeRecord | None:
    """
    Parse un XML `TEXTE_VERSION` DILA → `CodeRecord` si c'est un code juridique,
    None sinon (NATURE != CODE).

    On ne garde que les entrées `NATURE=CODE` pour peupler la table `codes`.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ParseError(f"XML mal formé: {exc}") from exc

    if root.tag != "TEXTE_VERSION":
        return None

    meta_commun = root.find("META/META_COMMUN")
    if meta_commun is None:
        return None
    nature = _text(meta_commun.find("NATURE"))
    if nature and nature.upper() != "CODE":
        return None

    chronicle = root.find("META/META_SPEC/META_TEXTE_CHRONICLE")
    version = root.find("META/META_SPEC/META_TEXTE_VERSION")
    if chronicle is None or version is None:
        return None

    cid = _text(chronicle.find("CID"))
    titre = _text(version.find("TITRE")) or _text(version.find("TITREFULL"))
    if not cid or not titre:
        return None
    date_maj = _text(chronicle.find("DERNIERE_MODIFICATION"))
    return CodeRecord(cid=cid, titre=titre, date_maj=date_maj)


def _iter_xml_entries(tarball: Path) -> Iterable[tuple[str, bytes, int]]:
    """
    Itère les entrées XML d'un .tar.gz DILA.

    Yield (nom_fichier, contenu_bytes, mtime). Les répertoires et fichiers
    non-.xml sont ignorés.
    """
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name
            if not name.endswith(".xml"):
                continue
            basename = name.rsplit("/", 1)[-1]
            if not basename.startswith("LEGI"):
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read()
            yield (basename, data, int(member.mtime))


def _upsert_article(conn: sqlite3.Connection, rec: ArticleRecord) -> str:
    """INSERT OR REPLACE article + retourne l'opération ('added'|'updated')."""
    cur = conn.execute("SELECT mtime FROM articles WHERE id = ?", (rec.id,))
    row = cur.fetchone()
    op = "updated" if row is not None else "added"
    conn.execute(
        """
        INSERT OR REPLACE INTO articles (
            id, code_cid, num, num_prefix, num_numeric,
            etat, date_debut, date_fin, texte, nota,
            url_legifrance, mtime
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rec.id, rec.code_cid, rec.num, rec.num_prefix, rec.num_numeric,
            rec.etat, rec.date_debut, rec.date_fin, rec.texte, rec.nota,
            rec.url_legifrance, rec.mtime,
        ),
    )
    return op


def _upsert_code(conn: sqlite3.Connection, rec: CodeRecord) -> None:
    conn.execute(
        """
        INSERT INTO codes (cid, titre, date_maj) VALUES (?, ?, ?)
        ON CONFLICT(cid) DO UPDATE SET
            titre    = excluded.titre,
            date_maj = excluded.date_maj
        """,
        (rec.cid, rec.titre, rec.date_maj),
    )


@dataclass
class ApplyStats:
    articles_added: int = 0
    articles_updated: int = 0
    articles_deleted: int = 0
    codes_upserted: int = 0
    parse_errors: int = 0


def apply_archive(
    tarball_path: Path,
    conn: sqlite3.Connection,
    keep_non_vigueur: bool = True,
) -> ApplyStats:
    """
    Applique le contenu d'un tarball DILA sur la DB ouverte.

    - Les fichiers ARTICLE sont upsertés dans `articles`.
    - Les fichiers TEXTE_VERSION de NATURE=CODE sont upsertés dans `codes`.
    - Les autres fichiers (SECTION_TA, liens, etc.) sont ignorés — on garde
      le minimum pour le retrieval.

    Si `keep_non_vigueur=False`, on filtre côté écriture les articles
    non en vigueur (politique retrieval plus stricte).
    """
    stats = ApplyStats()
    with conn:
        for basename, data, mtime in _iter_xml_entries(tarball_path):
            try:
                if basename.startswith("LEGIARTI"):
                    rec = parse_article_xml(data, mtime=mtime)
                    if not keep_non_vigueur and rec.etat != "VIGUEUR":
                        continue
                    op = _upsert_article(conn, rec)
                    if op == "added":
                        stats.articles_added += 1
                    else:
                        stats.articles_updated += 1
                elif basename.startswith("LEGITEXT"):
                    code_rec = parse_texte_version_xml(data)
                    if code_rec is not None:
                        _upsert_code(conn, code_rec)
                        stats.codes_upserted += 1
            except ParseError as exc:
                stats.parse_errors += 1
                logger.warning("parse error on %s: %s", basename, exc)
    return stats


def apply_suppression_list(
    tarball_path: Path, conn: sqlite3.Connection
) -> int:
    """
    Traite `liste_suppression_legi.dat` si présent dans le tarball.

    Format DILA : lignes `legi/global/code_et_TNC_*/.../LEGIARTI....xml`.
    On supprime les articles listés. Retourne le nombre d'articles supprimés.
    """
    deleted = 0
    with tarfile.open(tarball_path, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            if not member.name.endswith("liste_suppression_legi.dat"):
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            with conn:
                for line in extracted.read().decode("ascii", "replace").split():
                    basename = line.rsplit("/", 1)[-1]
                    if not basename.startswith("LEGIARTI"):
                        continue
                    article_id = basename[:-4] if basename.endswith(".xml") else basename
                    cur = conn.execute(
                        "DELETE FROM articles WHERE id = ?", (article_id,)
                    )
                    deleted += cur.rowcount
    return deleted
