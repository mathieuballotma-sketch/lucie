"""
PersonalMemory — Mémoire personnelle de l'utilisateur.

Couche 1/2 de l'architecture mémoire de Lucie.
Stocke les observations brutes : requêtes, dossiers clients, historique,
données sensibles. Reste locale pour toujours — ne sort jamais du disque
utilisateur. Chiffrée au repos à terme (TODO Bloc 3 : SQLCipher ou
chiffrement applicatif).

Salvagée depuis app/memory/context_graph.py (archive/pre-cleanup).
Modifications :
- Retrait de la dépendance app.utils.logger → logging stdlib
- Retrait du couplage EventBus (optionnel, mais simplifié)
- Interface publique normalisée : observe(), recall(), decay(), snapshot()
- Données séparées structurellement des patterns abstraits (AbstractMemory)

Ne jamais exporter les données brutes vers AbstractMemory directement :
passer impérativement par le sanitizer.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes plasticité synaptique (Hebbian LTP / LTD)
# ---------------------------------------------------------------------------
NODE_TYPES = {"preference", "skill", "goal", "relation", "pattern"}
EDGE_RELATIONS = {"related_to", "requires", "conflicts_with", "part_of"}

ARCHIVE_THRESHOLD = 0.1     # confidence < seuil → archivé (oubli LTD)
LTP_BOOST = 0.1             # gain de confiance par accès (LTP Hebbian)
DEFAULT_DECAY_RATE = 0.01   # 1 % de déclin par heure sans accès (LTD)
DEFAULT_CONFIDENCE = 0.5    # confiance initiale d'un nouveau nœud


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------

@dataclass
class ContextNode:
    """Nœud dans le graphe de contexte personnel."""
    id: str
    node_type: str
    content: str
    confidence: float
    created_at: float
    updated_at: float
    access_count: int
    decay_rate: float
    source: str


@dataclass
class ContextEdge:
    """Arête dans le graphe de contexte."""
    source_id: str
    target_id: str
    relation: str
    weight: float


# ---------------------------------------------------------------------------
# PersonalMemory
# ---------------------------------------------------------------------------

class PersonalMemory:
    """
    Graphe de contexte personnel — couche mémoire brute de Lucie.

    Apprend automatiquement depuis les interactions via observe().
    Plasticité synaptique LTP/LTD :
    - LTP : les nœuds accédés gagnent en confiance.
    - LTD : les nœuds non accédés perdent en confiance avec le temps.
    - Archivage : les nœuds < ARCHIVE_THRESHOLD sont archivés (oubli).

    Stockage : SQLite via aiosqlite (léger, async, pas de chargement complet).
    Données en clair — TODO Bloc 3 : chiffrement au repos.

    Usage :
        mem = PersonalMemory("data/personal.db")
        await mem.initialize()
        await mem.observe({"query": "licenciement économique", "domain": "licenciement"})
        results = await mem.recall("licenciement")
        profile = await mem.snapshot()
        await mem.close()
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Ouvre la connexion SQLite et crée le schéma si nécessaire."""
        await self._get_conn()

    async def close(self) -> None:
        """Ferme proprement la connexion SQLite."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "PersonalMemory":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Interface publique normalisée
    # ------------------------------------------------------------------

    async def observe(self, context: dict) -> str:
        """
        Enregistre une observation depuis le pipeline.

        Args:
            context: Dict avec au minimum "query" ou "content". Champs
                     optionnels : "domain", "source", "node_type".

        Returns:
            ID du nœud créé ou renforcé.
        """
        content = (
            context.get("query")
            or context.get("content")
            or context.get("text")
            or ""
        )
        if not content:
            return ""

        node_type = context.get("node_type", "pattern")
        if node_type not in NODE_TYPES:
            node_type = "pattern"
        source = context.get("source", "pipeline")

        return await self.learn(content=str(content), node_type=node_type, source=source)

    async def recall(self, query: str, top_k: int = 5) -> List[dict]:
        """
        Rappel des nœuds les plus pertinents pour une requête.

        Args:
            query: Texte de recherche.
            top_k: Nombre max de résultats.

        Returns:
            Liste de dicts avec content, confidence, node_type, source.
        """
        nodes = await self.query(query, top_k=top_k)
        return [
            {
                "content": n.content,
                "confidence": round(n.confidence, 3),
                "node_type": n.node_type,
                "source": n.source,
                "access_count": n.access_count,
            }
            for n in nodes
        ]

    async def decay(self, time_elapsed: float = 0.0) -> int:
        """
        Applique le déclin LTD et archive les nœuds sous le seuil.

        Args:
            time_elapsed: Ignoré — le déclin utilise le temps réel écoulé
                          depuis la dernière mise à jour de chaque nœud.

        Returns:
            Nombre de nœuds archivés.
        """
        return await self._apply_decay()

    async def snapshot(self) -> dict:
        """
        Retourne le profil utilisateur structuré par type de nœud.

        Utilisé pour "Ma fiche Beaume" dans l'onboarding et les rapports.
        Toutes les données sont datées et sourcées (garde-fou vérité).
        """
        return await self.get_user_profile()

    async def reset_all(self) -> int:
        """Drop tous les nœuds et arêtes du graphe personnel.

        Utilisé par le bouton « Effacer toute la mémoire » de la page
        « Ce que Beaume sait de vous » (Swiss watch — règle 6 transparence
        radicale). Action irréversible — la double confirmation utilisateur
        est gérée côté HUD (NSAlert avec saisie « EFFACER »).

        Returns:
            Nombre de nœuds supprimés (avant reset). Utile pour feedback UI.
        """
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT COUNT(*) FROM context_nodes")
        row = await cursor.fetchone()
        before = int(row[0]) if row else 0
        # Drop nœuds + arêtes. Ne touche pas le schema (init_schema reste idem).
        await conn.execute("DELETE FROM context_edges")
        await conn.execute("DELETE FROM context_nodes")
        await conn.commit()
        return before

    # ------------------------------------------------------------------
    # API bas niveau (ContextGraph interface préservée)
    # ------------------------------------------------------------------

    async def learn(
        self,
        content: str,
        node_type: str,
        source: str = "unknown",
        confidence: float = DEFAULT_CONFIDENCE,
        decay_rate: float = DEFAULT_DECAY_RATE,
    ) -> str:
        """
        Apprend une information ou renforce une connaissance existante (LTP).

        Si un nœud identique (même hash + type) existe, sa confiance est
        augmentée de LTP_BOOST. Sinon, un nouveau nœud est créé.
        """
        if node_type not in NODE_TYPES:
            node_type = "pattern"

        content_hash = self._content_hash(content)
        conn = await self._get_conn()
        now = time.time()

        cursor = await conn.execute(
            """SELECT id, confidence, access_count FROM context_nodes
               WHERE content_hash=? AND node_type=? AND archived=0""",
            (content_hash, node_type),
        )
        row = await cursor.fetchone()

        if row is not None:
            node_id: str = row["id"]
            new_confidence = min(1.0, row["confidence"] + LTP_BOOST)
            await conn.execute(
                """UPDATE context_nodes
                   SET confidence=?, access_count=?, updated_at=?
                   WHERE id=?""",
                (new_confidence, row["access_count"] + 1, now, node_id),
            )
            await conn.commit()
            return node_id

        node_id = str(uuid.uuid4())
        await conn.execute(
            """INSERT INTO context_nodes
               (id, node_type, content, content_hash, confidence,
                created_at, updated_at, access_count, decay_rate, source, archived)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (node_id, node_type, content, content_hash,
             confidence, now, now, 0, decay_rate, source),
        )
        await conn.commit()
        return node_id

    async def query(self, query_text: str, top_k: int = 5) -> List[ContextNode]:
        """Recherche textuelle des nœuds, pondérée par confidence."""
        words = [w for w in query_text.lower().split() if len(w) > 2]
        if not words:
            return []

        conn = await self._get_conn()
        conditions = " OR ".join(["LOWER(content) LIKE ?" for _ in words])
        params: List[Any] = [f"%{w}%" for w in words]
        params.append(top_k * 4)

        cursor = await conn.execute(
            f"""SELECT id, node_type, content, confidence, created_at, updated_at,
                       access_count, decay_rate, source
                FROM context_nodes
                WHERE archived=0 AND ({conditions})
                ORDER BY confidence DESC, access_count DESC
                LIMIT ?""",
            params,
        )
        rows = await cursor.fetchall()

        def relevance(row: Any) -> float:
            c = str(row["content"]).lower()
            matches = sum(1 for w in words if w in c)
            return float(matches * row["confidence"])

        sorted_rows = sorted(rows, key=relevance, reverse=True)
        return [self._row_to_node(r) for r in sorted_rows[:top_k]]

    async def reinforce(self, node_id: str) -> None:
        """LTP explicite sur un nœud connu."""
        conn = await self._get_conn()
        now = time.time()
        await conn.execute(
            """UPDATE context_nodes
               SET confidence = MIN(1.0, confidence + ?),
                   access_count = access_count + 1,
                   updated_at = ?
               WHERE id=? AND archived=0""",
            (LTP_BOOST, now, node_id),
        )
        await conn.commit()

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
    ) -> None:
        """Ajoute ou met à jour une relation entre deux nœuds."""
        if relation not in EDGE_RELATIONS:
            relation = "related_to"
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO context_edges (source_id, target_id, relation, weight)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (source_id, target_id, relation)
               DO UPDATE SET weight=excluded.weight""",
            (source_id, target_id, relation, weight),
        )
        await conn.commit()

    async def get_context_for(self, task_description: str, top_k: int = 5) -> str:
        """Contexte formaté en texte pour enrichir un prompt agent."""
        nodes = await self.query(task_description, top_k=top_k)
        if not nodes:
            return ""
        parts: List[str] = []
        for node in nodes:
            if node.confidence > 0.7:
                label = "haute"
            elif node.confidence > 0.4:
                label = "moyenne"
            else:
                label = "faible"
            parts.append(
                f"[{node.node_type.upper()}] {node.content} "
                f"(confiance {label}: {node.confidence:.2f})"
            )
        return "\n".join(parts)

    async def get_user_profile(self) -> Dict[str, Any]:
        """Profil structuré par type de nœud, avec statistiques globales."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT id, node_type, content, confidence, created_at, updated_at,
                      access_count, decay_rate, source
               FROM context_nodes WHERE archived=0
               ORDER BY confidence DESC, access_count DESC""",
        )
        rows = await cursor.fetchall()

        profile: Dict[str, Any] = {t: [] for t in NODE_TYPES}
        for row in rows:
            node = self._row_to_node(row)
            profile[node.node_type].append({
                "content": node.content,
                "confidence": round(node.confidence, 3),
                "access_count": node.access_count,
                "source": node.source,
                "created_at": datetime.fromtimestamp(node.created_at).isoformat(),
            })

        total = sum(len(v) for v in profile.values())
        profile["_stats"] = {
            "total_nodes": total,
            "generated_at": datetime.fromtimestamp(time.time()).isoformat(),
        }
        return profile

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            conn = await aiosqlite.connect(str(self._db_path))
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
            await self._init_schema(conn)
        return self._conn

    async def _init_schema(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS context_nodes (
                id           TEXT    PRIMARY KEY,
                node_type    TEXT    NOT NULL,
                content      TEXT    NOT NULL,
                content_hash TEXT    NOT NULL,
                confidence   REAL    NOT NULL DEFAULT 0.5,
                created_at   REAL    NOT NULL,
                updated_at   REAL    NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                decay_rate   REAL    NOT NULL DEFAULT 0.01,
                source       TEXT    NOT NULL DEFAULT 'unknown',
                archived     INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS context_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation  TEXT NOT NULL,
                weight    REAL NOT NULL DEFAULT 1.0,
                PRIMARY KEY (source_id, target_id, relation),
                FOREIGN KEY (source_id) REFERENCES context_nodes(id) ON DELETE CASCADE,
                FOREIGN KEY (target_id) REFERENCES context_nodes(id) ON DELETE CASCADE
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_node_type ON context_nodes(node_type)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_confidence ON context_nodes(confidence)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_content_hash ON context_nodes(content_hash)"
        )
        await conn.commit()

    async def _apply_decay(self) -> int:
        conn = await self._get_conn()
        now = time.time()
        await conn.execute(
            """UPDATE context_nodes
               SET confidence = MAX(0.0,
                   confidence - (decay_rate * (? - updated_at) / 3600.0)),
                   updated_at = ?
               WHERE archived=0""",
            (now, now),
        )
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM context_nodes WHERE confidence < ? AND archived=0",
            (ARCHIVE_THRESHOLD,),
        )
        count_row = await cursor.fetchone()
        archived_count = int(count_row[0]) if count_row else 0
        if archived_count > 0:
            await conn.execute(
                "UPDATE context_nodes SET archived=1 WHERE confidence < ? AND archived=0",
                (ARCHIVE_THRESHOLD,),
            )
        await conn.commit()
        return archived_count

    @staticmethod
    def _content_hash(content: str) -> str:
        normalized = content.strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    @staticmethod
    def _row_to_node(row: Any) -> ContextNode:
        return ContextNode(
            id=row["id"],
            node_type=row["node_type"],
            content=row["content"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            access_count=row["access_count"],
            decay_rate=row["decay_rate"],
            source=row["source"],
        )
