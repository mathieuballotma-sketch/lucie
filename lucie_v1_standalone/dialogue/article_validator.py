"""Early validation des références d'article — refus immédiat si l'article
n'existe pas dans la base Légifrance (ou dans la whitelist CT fallback).

Résout le cas « L.1234-999 existe-t-il ? » qui auparavant lançait le
pipeline complet (3 LLM séquentiels, ~11 s) avant de conclure par un refus.
Désormais : regex + résolveur déterministe = < 50 ms.

Architecture (Phase A Cerveau Oiseaux) :
  - `ArticleResolver` (ABC) : interface de vérification « un article existe-t-il ? ».
  - `SqliteLegifranceResolver` : implémentation SQLite Légifrance (SELECT indexé).
  - `WhitelistCtResolver` : fallback hardcodé des codes CT fréquents — engagé
    automatiquement quand la DB Légifrance est absente ou désactivée, ce qui
    garantit la promesse <1s même en mode dégradé.
  - `_default_resolver_chain()` compose la chaîne active à l'exécution.
  - V2 (ultérieure) ajoutera `WebWhitelistResolver` en queue de chaîne pour
    la résolution internet allowlist (legifrance.gouv.fr, courdecassation.fr,
    etc.) — zéro refactor pipeline.

Un article est considéré « inexistant » ssi AUCUN résolveur de la chaîne ne
le confirme. Cette règle donne la priorité à la DB Légifrance quand elle est
présente (elle peut invalider un code pourtant whitelisté mais non VIGUEUR),
et retombe sur la whitelist quand elle ne l'est pas.
"""

from __future__ import annotations

import abc
import logging
import re
import sqlite3
from functools import lru_cache
from typing import Optional

from lucie_v1_standalone.config import LEGIFRANCE_ENABLED, get_legifrance_db_path
from lucie_v1_standalone.dialogue.article_bounds import is_article_impossible
from lucie_v1_standalone.dialogue.whitelist_ct import is_whitelisted, whitelist_size

logger = logging.getLogger(__name__)

# Accepte : L.1234-1 | L 1234-1 | L1234-1 | L.1234 | R.1234-99 | L.1234-12345 ...
# Capture : (prefix, numeric, suffix_optionnel).
# Suffixe étendu à 5 chiffres (Cerveau Oiseaux v2) pour que le préfiltre
# bornes capture les formats fantaisistes type L.1234-12345 — la borne max
# DILA observée est 963, donc tout suffixe ≥ 4 chiffres est nécessairement
# rejeté par `is_article_impossible`. Pas d'effet de bord : aucun article
# en VIGUEUR dans la DILA n'a un suffixe à 5 chiffres.
ARTICLE_PATTERN = re.compile(
    r"\b([LR])\.?\s?(\d{3,4})(?:-(\d{1,5}))?\b",
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


# ─── Interface ArticleResolver ──────────────────────────────────────────────


class ArticleResolver(abc.ABC):
    """Interface d'un résolveur d'article.

    Une implémentation répond à une seule question : ce code d'article
    existe-t-il (en vigueur) ? Les détails (source, état, auteur) sont
    transparents pour le caller.
    """

    @abc.abstractmethod
    def exists(self, prefix: str, canonical: str) -> bool:
        """Retourne True si (prefix, canonical) existe en vigueur."""

    @abc.abstractmethod
    def name(self) -> str:
        """Identifiant court du résolveur pour logs/rapports (ex:
        'sqlite-legifrance', 'whitelist-ct')."""


class SqliteLegifranceResolver(ArticleResolver):
    """Résolveur basé sur la base SQLite Légifrance (DILA live).

    Source d'autorité : état VIGUEUR dans la table `articles`. Temps <50ms
    par requête grâce à l'index composite (num_prefix, num).
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def exists(self, prefix: str, canonical: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM articles "
            "WHERE num_prefix = ? AND num = ? AND etat = 'VIGUEUR' LIMIT 1",
            (prefix, canonical),
        )
        return cur.fetchone() is not None

    def name(self) -> str:
        return "sqlite-legifrance"


class WhitelistCtResolver(ArticleResolver):
    """Résolveur fallback basé sur la whitelist CT hardcodée.

    Toujours disponible (pas de dépendance fichier/réseau). Non exhaustif
    par construction — voir `whitelist_ct.py` pour les plages couvertes.
    """

    def exists(self, prefix: str, canonical: str) -> bool:
        return is_whitelisted(prefix, canonical)

    def name(self) -> str:
        return "whitelist-ct"


# ─── Connexion DB + chaîne par défaut ────────────────────────────────────────

_WARNING_EMITTED = False


def _emit_degraded_warning(reason: str) -> None:
    """Affiche une bannière WARNING une seule fois quand Légifrance est
    indisponible. Idempotent via un flag module."""
    global _WARNING_EMITTED
    if _WARNING_EMITTED:
        return
    _WARNING_EMITTED = True
    logger.warning(
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃ ⚠️  Légifrance SQLite indisponible → mode dégradé actif          ┃\n"
        "┃    Raison : %-52s┃\n"
        "┃ Fallback whitelist CT (%d codes) engagé pour garantir <1s.  ┃\n"
        "┃ Articles récents/obscurs non whitelistés : résolution imprécise. ┃\n"
        "┃ Activer : export BEAUME_LEGIFRANCE=1 + synchroniser la DB DILA.  ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
        reason[:52],
        whitelist_size(),
    )


@lru_cache(maxsize=1)
def _db_connection() -> Optional[sqlite3.Connection]:
    """Connexion SQLite read-only cachée. Retourne None si Légifrance est
    désactivée ou la DB absente — le caller active le fallback whitelist."""
    if not LEGIFRANCE_ENABLED:
        _emit_degraded_warning("BEAUME_LEGIFRANCE=0 (env var non activée)")
        return None
    db_path = get_legifrance_db_path()
    if not db_path.exists():
        _emit_degraded_warning(f"DB introuvable à {db_path}")
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
        _emit_degraded_warning(f"ouverture DB échouée : {exc}")
        return None


def _default_resolver_chain() -> list[ArticleResolver]:
    """Compose la chaîne active de résolveurs.

    Ordre d'évaluation : DB Légifrance d'abord (si disponible, elle est
    source d'autorité), whitelist CT ensuite (garantit la promesse <1s).

    V2 ajoutera `WebWhitelistResolver` en queue (couverture articles
    récents/obscurs via allowlist internet).
    """
    chain: list[ArticleResolver] = []
    conn = _db_connection()
    if conn is not None:
        chain.append(SqliteLegifranceResolver(conn))
    chain.append(WhitelistCtResolver())
    return chain


def validate_article_refs(
    query: str,
    resolver_chain: Optional[list[ArticleResolver]] = None,
) -> Optional[str]:
    """Retourne le message de refus si au moins une ref article de `query`
    n'existe dans AUCUN résolveur de la chaîne. None sinon (passthrough).

    Args:
        query: texte libre à scanner.
        resolver_chain: chaîne de résolveurs à utiliser. Par défaut, compose
            dynamiquement via `_default_resolver_chain()` (Légifrance +
            whitelist CT selon disponibilité).
    """
    if not query or not query.strip():
        return None

    codes = extract_article_codes(query)
    if not codes:
        return None

    # Idempotent (lru_cache) — émet le WARNING "mode dégradé" si Légifrance
    # est désactivée ou DB absente. Doit être appelé AVANT le préfiltre pour
    # que la bannière soit visible même quand le préfiltre court-circuite la
    # chain (sinon le warning serait masqué sur les refus instantanés).
    if resolver_chain is None:
        _db_connection()

    # ─── GATE 0 : préfiltre bornes numériques (Cerveau Oiseaux v2) ──────────
    # Refuse en <1ms les articles mathématiquement impossibles, AVANT tout
    # I/O SQLite. Ex: L.1234-999 quand la racine L.1234-x s'arrête à 20.
    # Source d'autorité : article_bounds_data.py (généré depuis DILA).
    for prefix, canonical, display in codes:
        impossible, raison = is_article_impossible(display)
        if impossible:
            logger.info(
                "[EarlyValidation] article=%s impossible par bornes (%s) → refus immédiat",
                display,
                raison,
            )
            return _REFUSAL_TEMPLATE.format(display=display)

    chain = resolver_chain if resolver_chain is not None else _default_resolver_chain()
    if not chain:
        # Aucun résolveur → impossible de statuer, on laisse passer.
        return None

    for prefix, canonical, display in codes:
        if not any(r.exists(prefix, canonical) for r in chain):
            logger.info(
                "[EarlyValidation] article=%s exists=False (résolveurs: %s) → refus immédiat",
                display,
                ",".join(r.name() for r in chain),
            )
            return _REFUSAL_TEMPLATE.format(display=display)

    return None


def active_resolver_names() -> list[str]:
    """Liste les noms des résolveurs actifs (utilitaire pour logs/rapport).

    Ne démarre pas la chaîne si elle n'est pas nécessaire — appelle
    directement `_default_resolver_chain()` et retourne les noms.
    """
    return [r.name() for r in _default_resolver_chain()]


def clear_validator_cache() -> None:
    """Ferme la connexion cachée et réinitialise le flag WARNING — utile
    pour tests qui manipulent la DB ou rechargent la config."""
    global _WARNING_EMITTED
    info = _db_connection.cache_info()
    if info.currsize > 0:
        cached = _db_connection()
        if cached is not None:
            try:
                cached.close()
            except sqlite3.Error:
                pass
    _db_connection.cache_clear()
    _WARNING_EMITTED = False


__all__ = [
    "ARTICLE_PATTERN",
    "ArticleResolver",
    "SqliteLegifranceResolver",
    "WhitelistCtResolver",
    "active_resolver_names",
    "clear_validator_cache",
    "extract_article_codes",
    "validate_article_refs",
]
