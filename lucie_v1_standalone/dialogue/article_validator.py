"""Early validation des références d'article — refus immédiat si l'article
n'existe pas dans la base Légifrance.

Résout le cas « L.1234-999 existe-t-il ? » qui auparavant lançait le
pipeline complet (3 LLM séquentiels, ~1 min 30 s) avant de conclure
par un refus. Désormais : regex + 1 SELECT indexé = < 50 ms.

Stratégie :
  1. Regex `ARTICLE_PATTERN` extrait les codes articles mentionnés
     (L.1234-1, R 1234-1, L1234, etc.).
  2. Pour chaque code, SELECT 1 sur la table `articles` de Légifrance
     (index composite num_prefix + num).
  3. Si au moins un code extrait n'existe pas → retourne le message de
     refus honnête ; sinon None (passthrough, pipeline continue).

Mode dégradé (LUCIE_LEGIFRANCE=0 ou DB absente) : no-op silencieux
avec `logger.warning` — on accepte que les LLM aval puissent halluciner,
le fallback est acceptable en attendant l'activation Légifrance. Cet
écart est documenté ; Mathieu active LEGIFRANCE en production.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from functools import lru_cache
from typing import Optional

from lucie_v1_standalone.config import LEGIFRANCE_ENABLED, get_legifrance_db_path

logger = logging.getLogger(__name__)

# Accepte : L.1234-1 | L 1234-1 | L1234-1 | L.1234 | R.1234-99 ...
# Capture : (prefix, numeric, suffix_optionnel)
ARTICLE_PATTERN = re.compile(
    r"\b([LR])\.?\s?(\d{3,4})(?:-(\d{1,4}))?\b",
    re.IGNORECASE,
)

_REFUSAL_TEMPLATE = (
    "L'article {display} n'existe pas dans le Code du travail.\n"
    "Je préfère vous le dire clairement plutôt que d'inventer un contenu.\n"
    "\n"
    "Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider "
    "si vous précisez la thématique."
)


def extract_article_codes(query: str) -> list[tuple[str, str, str]]:
    """Extrait les références d'articles de `query`.

    Retourne `[(prefix, canonical_num, display_form), ...]` où :
      - `prefix` : "L" ou "R" (majuscule)
      - `canonical_num` : format DB, ex "L1234-999" ou "L1234"
      - `display_form` : format utilisateur, ex "L.1234-999"
    """
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for m in ARTICLE_PATTERN.finditer(query):
        prefix = m.group(1).upper()
        numeric = m.group(2)
        suffix = m.group(3)
        if suffix:
            canonical = f"{prefix}{numeric}-{suffix}"
            display = f"{prefix}.{numeric}-{suffix}"
        else:
            canonical = f"{prefix}{numeric}"
            display = f"{prefix}.{numeric}"
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append((prefix, canonical, display))
    return out


@lru_cache(maxsize=1)
def _db_connection() -> Optional[sqlite3.Connection]:
    """Connexion SQLite read-only cachée. Retourne None si Légifrance est
    désactivée ou la DB absente — le caller interprète comme no-op."""
    if not LEGIFRANCE_ENABLED:
        logger.debug("[ArticleValidator] LUCIE_LEGIFRANCE=0, validation désactivée")
        return None
    db_path = get_legifrance_db_path()
    if not db_path.exists():
        logger.warning(
            "[ArticleValidator] DB Légifrance introuvable à %s, validation désactivée",
            db_path,
        )
        return None
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.DatabaseError as exc:
        logger.warning("[ArticleValidator] ouverture DB échouée : %s", exc)
        return None


def _article_exists(conn: sqlite3.Connection, prefix: str, canonical: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM articles "
        "WHERE num_prefix = ? AND num = ? AND etat = 'VIGUEUR' LIMIT 1",
        (prefix, canonical),
    )
    return cur.fetchone() is not None


def validate_article_refs(query: str) -> Optional[str]:
    """Retourne le message de refus si au moins une ref article de `query`
    n'existe pas dans la base Légifrance. None si tous existent, si aucune
    ref n'est trouvée, ou si la DB n'est pas disponible (mode dégradé)."""
    if not query or not query.strip():
        return None

    codes = extract_article_codes(query)
    if not codes:
        return None

    conn = _db_connection()
    if conn is None:
        # Mode dégradé documenté : on ne peut pas valider, on laisse passer.
        return None

    for prefix, canonical, display in codes:
        if not _article_exists(conn, prefix, canonical):
            logger.info(
                "[EarlyValidation] article=%s exists=False → refus immédiat",
                display,
            )
            return _REFUSAL_TEMPLATE.format(display=display)

    return None


def clear_validator_cache() -> None:
    """Ferme la connexion cachée — utile pour tests qui manipulent la DB."""
    conn = _db_connection.cache_info()
    if conn.currsize > 0:
        cached = _db_connection()
        if cached is not None:
            try:
                cached.close()
            except sqlite3.Error:
                pass
    _db_connection.cache_clear()


__all__ = [
    "ARTICLE_PATTERN",
    "extract_article_codes",
    "validate_article_refs",
    "clear_validator_cache",
]
