"""
AbstractMemory — Mémoire des patterns abstraits partageable.

Couche 2/2 de l'architecture mémoire de Lucie.

Stocke uniquement des patterns anonymisés :
- Aucun nom, montant, date précise, numéro de dossier
- Uniquement la structure abstraite : domaine, fréquence, signal
- Prête pour le partage P2P (Bloc N+2) sans modification de cette interface

Règle d'accès :
- PersonalMemory → sanitizer → AbstractMemory   ✅
- AbstractMemory → PersonalMemory               ❌ jamais

Les patterns accumulent du signal via LTP (même mécanisme que PersonalMemory)
mais le contenu ne contient que des informations abstraites.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Seuil d'activation — le pattern doit atteindre ce score de signal avant
# d'être visible via patterns_above_threshold(). Bloc 2 lira ce seuil
# pour déclencher ProactiveEngine.
SIGNAL_ACTIVATION_THRESHOLD = 0.7

# LTP/LTD partagés — cohérence avec PersonalMemory
PATTERN_LTP_BOOST = 0.12
PATTERN_DEFAULT_CONFIDENCE = 0.3  # Plus bas car signal doit être mérité
PATTERN_DECAY_RATE = 0.005        # Déclin plus lent que PersonalMemory


@dataclass
class AbstractPattern:
    """Pattern abstrait — aucune PII."""
    id: str
    domain: str           # "licenciement", "rémunération", etc.
    pattern_text: str     # Texte anonymisé (sans PII)
    signal: float         # 0.0 → 1.0 (confiance / fréquence accumulée)
    hit_count: int        # Nombre de fois que ce pattern a été renforcé
    created_at: float
    updated_at: float


class AbstractMemory:
    """
    Mémoire des patterns abstraits — couche partageable.

    Accumule du signal sur les patterns de raisonnement sans stocker
    aucune donnée personnelle. Prête pour P2P dans Bloc N+2.

    La couche P2P s'injectera ici (export/import via un canal chiffré X25519).
    Cette interface ne changera pas.

    Usage :
        mem = AbstractMemory("data/abstract.db")
        mem.initialize()
        mem.accumulate("licenciement", "requête sur [TYPE_REQUÊTE] avec [DOMAINE]")
        patterns = mem.patterns_above_threshold()
        mem.close()

    Note : interface synchrone (sqlite3 stdlib) — pas de dépendance async
    pour simplifier l'export P2P futur.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Ouvre la connexion et crée le schéma."""
        if self._conn is None:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn = conn
            self._init_schema(conn)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "AbstractMemory":
        self.initialize()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def accumulate(self, domain: str, pattern_text: str) -> str:
        """
        Accumule du signal pour un pattern abstrait (LTP).

        Le pattern_text doit déjà être anonymisé (passé par sanitizer).
        Si un pattern identique existe dans ce domaine, son signal augmente.
        Sinon, un nouveau pattern est créé avec signal initial bas.

        Args:
            domain: Domaine détecté ("licenciement", "rémunération", …).
            pattern_text: Texte anonymisé — aucune PII autorisée ici.

        Returns:
            ID du pattern créé ou renforcé.
        """
        conn = self._get_conn()
        content_hash = _hash(domain + "|" + pattern_text)
        now = time.time()

        row = conn.execute(
            "SELECT id, signal, hit_count FROM abstract_patterns WHERE content_hash=?",
            (content_hash,),
        ).fetchone()

        if row is not None:
            pattern_id: str = row["id"]
            new_signal = min(1.0, row["signal"] + PATTERN_LTP_BOOST)
            conn.execute(
                "UPDATE abstract_patterns SET signal=?, hit_count=?, updated_at=? WHERE id=?",
                (new_signal, row["hit_count"] + 1, now, pattern_id),
            )
            conn.commit()
            return pattern_id

        pattern_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO abstract_patterns
               (id, domain, pattern_text, content_hash, signal, hit_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pattern_id, domain, pattern_text, content_hash,
             PATTERN_DEFAULT_CONFIDENCE, 1, now, now),
        )
        conn.commit()
        return pattern_id

    def patterns_above_threshold(
        self,
        threshold: float = SIGNAL_ACTIVATION_THRESHOLD,
        domain: Optional[str] = None,
    ) -> List[AbstractPattern]:
        """
        Retourne les patterns dont le signal dépasse le seuil d'activation.

        Bloc 2 (ProactiveEngine) lira cette liste pour déclencher des
        propositions proactives à l'utilisateur.

        Args:
            threshold: Seuil de signal (défaut : SIGNAL_ACTIVATION_THRESHOLD).
            domain: Filtre optionnel par domaine.

        Returns:
            Liste de AbstractPattern triée par signal décroissant.
        """
        conn = self._get_conn()
        if domain:
            rows = conn.execute(
                """SELECT * FROM abstract_patterns
                   WHERE signal >= ? AND domain = ?
                   ORDER BY signal DESC""",
                (threshold, domain),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM abstract_patterns
                   WHERE signal >= ?
                   ORDER BY signal DESC""",
                (threshold,),
            ).fetchall()

        return [_row_to_pattern(r) for r in rows]

    def all_patterns(self, domain: Optional[str] = None) -> List[AbstractPattern]:
        """Retourne tous les patterns (sous le seuil inclus)."""
        conn = self._get_conn()
        if domain:
            rows = conn.execute(
                "SELECT * FROM abstract_patterns WHERE domain=? ORDER BY signal DESC",
                (domain,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM abstract_patterns ORDER BY signal DESC"
            ).fetchall()
        return [_row_to_pattern(r) for r in rows]

    def signal_by_domain(self) -> Dict[str, float]:
        """
        Retourne le signal agrégé par domaine.

        Utilisé pour diagnostiquer la spécialisation de l'instance Lucie.
        """
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT domain, AVG(signal) as avg_signal, COUNT(*) as n
               FROM abstract_patterns GROUP BY domain ORDER BY avg_signal DESC"""
        ).fetchall()
        return {
            r["domain"]: round(r["avg_signal"], 3)
            for r in rows
        }

    def apply_decay(self) -> None:
        """Déclin LTD — réduit le signal des patterns non renforcés."""
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            """UPDATE abstract_patterns
               SET signal = MAX(0.0, signal - (? * (? - updated_at) / 3600.0)),
                   updated_at = ?
               WHERE signal > 0""",
            (PATTERN_DECAY_RATE, now, now),
        )
        conn.commit()

    def export_for_p2p(self) -> List[dict]:
        """
        Exporte les patterns au-dessus du seuil pour partage P2P futur.

        Retourne uniquement domaine + pattern_text + signal — aucun ID local,
        aucune métadonnée temporelle liée à l'utilisateur.
        Cette méthode sera l'unique point d'entrée de la couche P2P (Bloc N+2).
        """
        return [
            {"domain": p.domain, "pattern": p.pattern_text, "signal": round(p.signal, 3)}
            for p in self.patterns_above_threshold()
        ]

    def clear(self) -> int:
        """Drop tous les patterns abstraits (Swiss watch — règle 6).

        Sync (sqlite3 standard, pas async) — appelée depuis MemoryStore.reset().
        Retourne le nombre de patterns avant clear.
        """
        conn = self._get_conn()
        cur = conn.execute("SELECT COUNT(*) FROM abstract_patterns")
        before = int(cur.fetchone()[0])
        conn.execute("DELETE FROM abstract_patterns")
        conn.commit()
        return before

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.initialize()
        assert self._conn is not None
        return self._conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS abstract_patterns (
                id           TEXT PRIMARY KEY,
                domain       TEXT NOT NULL,
                pattern_text TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                signal       REAL NOT NULL DEFAULT 0.3,
                hit_count    INTEGER NOT NULL DEFAULT 1,
                created_at   REAL NOT NULL,
                updated_at   REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON abstract_patterns(domain)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal ON abstract_patterns(signal)")
        conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]


def _row_to_pattern(row: sqlite3.Row) -> AbstractPattern:
    return AbstractPattern(
        id=row["id"],
        domain=row["domain"],
        pattern_text=row["pattern_text"],
        signal=row["signal"],
        hit_count=row["hit_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
