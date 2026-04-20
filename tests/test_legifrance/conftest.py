"""
Fixtures partagées pour les tests Légifrance.

Construit un mini-tarball in-memory avec 6 articles canoniques (un par thème)
+ 2 codes juridiques. Aucune dépendance réseau, ≤10 KB sur disque.

Les IDs LEGIARTI/LEGITEXT ici sont synthétiques (pas les vrais CID DILA),
conçus pour correspondre au theme_mapping.yaml :
    - LEGITEXT000006072050 (Code du travail)     → L1234-1, R1411-2
    - LEGITEXT000005634379 (Code de commerce)    → L145-8, L225-1
    - LEGITEXT000006070721 (Code civil)          → 212-0
    - LEGITEXT000006069577 (CGI)                 → 256-1 (prefix "", numeric 256)
"""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path
from typing import Iterable

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"

# (cid, titre)
_CODES = [
    ("LEGITEXT000006072050", "Code du travail"),
    ("LEGITEXT000005634379", "Code de commerce"),
    ("LEGITEXT000006070721", "Code civil"),
    ("LEGITEXT000006069577", "Code général des impôts"),
]

# (id, code_cid, num, etat, date_debut, texte, nota)
_ARTICLES = [
    (
        "LEGIARTI000090001234",
        "LEGITEXT000006072050",
        "L1234-1",
        "VIGUEUR",
        "2020-01-01",
        "Le délai de préavis de licenciement pour motif personnel est fixé "
        "par la convention collective. À défaut, il est d'un mois pour un "
        "salarié ayant entre six mois et deux ans d'ancienneté, et de deux "
        "mois pour plus de deux ans.",
        "Article modifié par la loi du 1er janvier 2020.",
    ),
    (
        "LEGIARTI000090001411",
        "LEGITEXT000006072050",
        "R1411-2",
        "VIGUEUR",
        "2018-06-01",
        "La saisine du conseil de prud'hommes s'effectue par requête remise "
        "ou adressée au greffe du conseil compétent. La requête contient, "
        "à peine de nullité, les mentions prescrites par l'article 58 du "
        "code de procédure civile.",
        None,
    ),
    (
        "LEGIARTI000090145008",
        "LEGITEXT000005634379",
        "L145-8",
        "VIGUEUR",
        "2014-07-01",
        "Le bail commercial renouvelé prend effet à la date d'expiration du "
        "bail précédent ou, le cas échéant, de sa prolongation. Sa durée "
        "est de neuf années sauf accord des parties pour une durée plus longue.",
        None,
    ),
    (
        "LEGIARTI000090225001",
        "LEGITEXT000005634379",
        "L225-1",
        "VIGUEUR",
        "2000-09-01",
        "La société anonyme est la société dont le capital est divisé en "
        "actions et qui est constituée entre des associés qui ne supportent "
        "les pertes qu'à concurrence de leurs apports.",
        None,
    ),
    (
        "LEGIARTI000090000212",
        "LEGITEXT000006070721",
        "212",
        "VIGUEUR",
        "1803-03-15",
        "Les époux se doivent mutuellement respect, fidélité, secours et assistance.",
        None,
    ),
    (
        "LEGIARTI000090000256",
        "LEGITEXT000006069577",
        "256",
        "VIGUEUR",
        "1979-01-01",
        "Sont soumises à la taxe sur la valeur ajoutée les livraisons de "
        "biens et les prestations de services effectuées à titre onéreux par "
        "un assujetti agissant en tant que tel.",
        None,
    ),
]


def _article_xml(
    article_id: str,
    code_cid: str,
    num: str,
    etat: str,
    date_debut: str,
    texte: str,
    nota: str | None,
) -> bytes:
    nota_block = (
        f"<NOTA><CONTENU>{nota}</CONTENU></NOTA>" if nota else ""
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ARTICLE>
  <META>
    <META_COMMUN>
      <ID>{article_id}</ID>
      <NATURE>Article</NATURE>
    </META_COMMUN>
    <META_SPEC>
      <META_ARTICLE>
        <NUM>{num}</NUM>
        <ETAT>{etat}</ETAT>
        <DATE_DEBUT>{date_debut}</DATE_DEBUT>
        <DATE_FIN>2999-01-01</DATE_FIN>
        <TYPE>AUTONOME</TYPE>
      </META_ARTICLE>
    </META_SPEC>
  </META>
  <CONTEXTE>
    <TEXTE cid="{code_cid}">
      <TITRE_TXT id="t"/>
    </TEXTE>
  </CONTEXTE>
  <BLOC_TEXTUEL>
    <CONTENU>{texte}</CONTENU>
  </BLOC_TEXTUEL>
  {nota_block}
</ARTICLE>
"""
    return xml.encode("utf-8")


def _texte_version_xml(cid: str, titre: str) -> bytes:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<TEXTE_VERSION>
  <META>
    <META_COMMUN>
      <ID>{cid}</ID>
      <NATURE>CODE</NATURE>
    </META_COMMUN>
    <META_SPEC>
      <META_TEXTE_CHRONICLE>
        <CID>{cid}</CID>
        <DERNIERE_MODIFICATION>2026-04-15</DERNIERE_MODIFICATION>
      </META_TEXTE_CHRONICLE>
      <META_TEXTE_VERSION>
        <TITRE>{titre}</TITRE>
        <TITREFULL>{titre}</TITREFULL>
        <ETAT>VIGUEUR</ETAT>
        <DATE_DEBUT>1970-01-01</DATE_DEBUT>
      </META_TEXTE_VERSION>
    </META_SPEC>
  </META>
</TEXTE_VERSION>
"""
    return xml.encode("utf-8")


def _build_tarball(
    dest: Path,
    articles: Iterable[tuple] = _ARTICLES,
    codes: Iterable[tuple[str, str]] = _CODES,
    suppression: list[str] | None = None,
) -> Path:
    """Build a DILA-shaped .tar.gz with XML files. Idempotent."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    buf = io.BytesIO()
    with tarfile.open(dest, "w:gz") as tar:
        # Codes (LEGITEXT...xml)
        for cid, titre in codes:
            data = _texte_version_xml(cid, titre)
            path = f"legi/global/code_et_TNC_en_vigueur/TNC_en_vigueur/{cid}.xml"
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            info.mtime = now
            tar.addfile(info, io.BytesIO(data))
        # Articles (LEGIARTI...xml)
        for rec in articles:
            article_id = rec[0]
            data = _article_xml(*rec)
            path = (
                "legi/global/code_et_TNC_en_vigueur/TNC_en_vigueur/"
                f"article/{article_id[:8]}/{article_id[8:12]}/"
                f"{article_id[12:16]}/{article_id}.xml"
            )
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            info.mtime = now
            tar.addfile(info, io.BytesIO(data))
        # Suppression list (optional)
        if suppression:
            sup_data = "\n".join(suppression).encode("ascii")
            info = tarfile.TarInfo(name="legi/liste_suppression_legi.dat")
            info.size = len(sup_data)
            info.mtime = now
            tar.addfile(info, io.BytesIO(sup_data))
    return dest


@pytest.fixture(scope="session")
def sample_tarball(tmp_path_factory) -> Path:
    """Un tarball full-style avec 6 articles + 4 codes."""
    path = tmp_path_factory.mktemp("legi_fixtures") / "LEGI_sample_20260418.tar.gz"
    return _build_tarball(path)


@pytest.fixture
def incremental_tarball(tmp_path) -> Path:
    """
    Tarball incrémental : mêmes 6 articles mais l'un est modifié (L1234-1
    avec un nouveau texte) et un autre est supprimé via liste_suppression.
    """
    updated = list(_ARTICLES)
    # Modifier L1234-1 : nouveau texte
    updated[0] = (
        updated[0][0], updated[0][1], updated[0][2], updated[0][3],
        updated[0][4],
        "Texte modifié — le délai de préavis est désormais fixé à 3 mois.",
        updated[0][6],
    )
    # Supprimer R1411-2
    suppression = [
        f"legi/global/code_et_TNC_en_vigueur/TNC_en_vigueur/article/LEGIARTI/0000/9000/{updated[1][0]}.xml"
    ]
    # Retirer aussi l'article du tarball (incrémental ne le retransmet pas)
    without_deleted = [a for a in updated if a[0] != updated[1][0]]
    path = tmp_path / "LEGI_20260419-210000.tar.gz"
    return _build_tarball(path, articles=without_deleted, suppression=suppression)


@pytest.fixture
def seeded_db(tmp_path, sample_tarball) -> Path:
    """Retourne un chemin de DB pré-alimentée avec les 6 articles + thèmes."""
    from lucie_v1_standalone.knowledge_legifrance.parser import (
        apply_archive,
        init_db,
    )
    from lucie_v1_standalone.knowledge_legifrance.indexer import reindex_themes

    db_path = tmp_path / "legi.sqlite"
    conn = init_db(db_path)
    try:
        apply_archive(sample_tarball, conn)
        reindex_themes(conn)
    finally:
        conn.close()
    return db_path
