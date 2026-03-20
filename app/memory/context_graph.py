"""
Graphe de Contexte Personnel — Le moat n°1 de Lucie.

Modèle mental structuré de l'utilisateur qui s'enrichit au fil du temps.
Bio-inspiré par la plasticité synaptique :
- LTP (potentiation à long terme) : les nœuds accédés gagnent en confiance.
- LTD (dépression à long terme) : les nœuds non accédés perdent en confiance.
- Archivage : les nœuds dont la confiance tombe sous 0.1 sont archivés.

Stockage : SQLite via aiosqlite (léger, pas de chargement complet en mémoire).
"""

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from app.utils.logger import logger

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
NODE_TYPES = {"preference", "skill", "goal", "relation", "pattern"}
EDGE_RELATIONS = {"related_to", "requires", "conflicts_with", "part_of"}

ARCHIVE_THRESHOLD = 0.1   # confidence < seuil → archivé
LTP_BOOST = 0.1           # gain de confiance par accès (Hebbian LTP)
DEFAULT_DECAY_RATE = 0.01  # 1 % de déclin par heure sans accès (Hebbian LTD)
DEFAULT_CONFIDENCE = 0.5   # confiance initiale d'un nouveau nœud


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------
@dataclass
class ContextNode:
    """Nœud dans le graphe de contexte personnel."""

    id: str
    node_type: str        # "preference", "skill", "goal", "relation", "pattern"
    content: str
    confidence: float     # 0.0 à 1.0
    created_at: float     # timestamp POSIX
    updated_at: float     # timestamp POSIX
    access_count: int
    decay_rate: float     # taux de déclin par heure
    source: str           # origine de l'information


@dataclass
class ContextEdge:
    """Arête dans le graphe de contexte."""

    source_id: str
    target_id: str
    relation: str   # "related_to", "requires", "conflicts_with", "part_of"
    weight: float


# ---------------------------------------------------------------------------
# Classe principale
# ---------------------------------------------------------------------------
class ContextGraph:
    """
    Graphe de Contexte Personnel.

    Apprend automatiquement depuis les interactions utilisateur via l'EventBus
    et permet d'interroger le profil utilisateur pour enrichir les réponses.

    Usage :
        graph = ContextGraph("data/context.db")
        await graph.initialize(event_bus)   # optionnel
        node_id = await graph.learn("Python", "skill", source="user")
        nodes = await graph.query("développement Python")
        profile = await graph.get_user_profile()
    """

    def __init__(self, db_path: str) -> None:
        """
        Args:
            db_path: Chemin vers la base de données SQLite à utiliser.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[aiosqlite.Connection] = None
        self._event_bus: Optional[Any] = None
        self._token: Optional[str] = None
        self._source = "context_graph"

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    async def _get_conn(self) -> aiosqlite.Connection:
        """Retourne la connexion SQLite, en la créant si nécessaire."""
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
        """Crée les tables si elles n'existent pas encore."""
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
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_node_type ON context_nodes(node_type)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_confidence ON context_nodes(confidence)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_content_hash ON context_nodes(content_hash)"
        )
        await conn.commit()

    async def initialize(self, event_bus: Optional[Any] = None) -> None:
        """
        Initialise le graphe : connexion SQLite + abonnement EventBus optionnel.

        Args:
            event_bus: Instance d'EventBus pour l'intégration (optionnel).
        """
        await self._get_conn()

        if event_bus is None:
            return

        self._event_bus = event_bus
        try:
            self._token = await event_bus.register_source(
                source=self._source,
                publish_channels=["context_update"],
                subscribe_channels=["user_interaction"],
            )
            token = self._token
            if token is not None:
                await event_bus.subscribe(
                    channel="user_interaction",
                    callback=self._on_user_interaction,
                    source=self._source,
                    token=token,
                )
            logger.info("ContextGraph connecté à l'EventBus")
        except Exception as e:
            logger.warning(f"ContextGraph: impossible de se connecter à l'EventBus: {e}")
            self._event_bus = None
            self._token = None

    # ------------------------------------------------------------------
    # Handler EventBus
    # ------------------------------------------------------------------
    async def _on_user_interaction(self, event: Any) -> None:
        """Apprend automatiquement depuis les événements d'interaction utilisateur."""
        try:
            data = getattr(event, "data", {})
            if not isinstance(data, dict):
                return

            content = data.get("query") or data.get("content") or data.get("text")
            if not content:
                return

            node_type = data.get("node_type", "pattern")
            if node_type not in NODE_TYPES:
                node_type = "pattern"

            event_source = getattr(event, "source", "user_interaction")
            source = data.get("source", event_source)

            await self.learn(content=str(content), node_type=node_type, source=source)
        except Exception as e:
            logger.error(f"ContextGraph._on_user_interaction erreur: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _content_hash(content: str) -> str:
        """Hash normalisé du contenu pour déduplication."""
        normalized = content.strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    @staticmethod
    def _row_to_node(row: Any) -> ContextNode:
        """Convertit une ligne aiosqlite.Row en ContextNode."""
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

    # ------------------------------------------------------------------
    # API publique
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
        Apprend une nouvelle information ou renforce une connaissance existante.

        Si un nœud avec le même contenu et type existe déjà, sa confiance
        est augmentée (LTP). Sinon, un nouveau nœud est créé.

        Args:
            content: Contenu de l'information à mémoriser.
            node_type: Type de nœud parmi NODE_TYPES.
            source: Origine de l'information.
            confidence: Confiance initiale (0.0–1.0).
            decay_rate: Taux de déclin par heure (LTD).

        Returns:
            ID du nœud créé ou mis à jour.
        """
        if node_type not in NODE_TYPES:
            node_type = "pattern"

        content_hash = self._content_hash(content)
        conn = await self._get_conn()
        now = time.time()

        # Vérifier si un nœud similaire existe déjà (même hash + type)
        cursor = await conn.execute(
            """SELECT id, confidence, access_count FROM context_nodes
               WHERE content_hash=? AND node_type=? AND archived=0""",
            (content_hash, node_type),
        )
        row = await cursor.fetchone()

        if row is not None:
            # Nœud existant → LTP
            node_id: str = row["id"]
            new_confidence = min(1.0, row["confidence"] + LTP_BOOST)
            new_access = row["access_count"] + 1
            await conn.execute(
                """UPDATE context_nodes
                   SET confidence=?, access_count=?, updated_at=?
                   WHERE id=?""",
                (new_confidence, new_access, now, node_id),
            )
            await conn.commit()
            await self._publish_update("node_reinforced", node_id)
            return node_id

        # Nouveau nœud
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
        await self._publish_update("node_created", node_id)
        logger.debug(f"ContextGraph: nouveau nœud '{node_type}' créé ({node_id[:8]}…)")
        return node_id

    async def query(self, query_text: str, top_k: int = 5) -> List[ContextNode]:
        """
        Recherche les nœuds les plus pertinents pour une requête textuelle.

        Utilise une recherche LIKE sur le contenu, pondérée par confidence
        et nombre de mots correspondants.

        Args:
            query_text: Texte de recherche.
            top_k: Nombre maximum de résultats.

        Returns:
            Liste de ContextNode triés par pertinence décroissante.
        """
        words = [w for w in query_text.lower().split() if w]
        if not words:
            return []

        conn = await self._get_conn()
        conditions = " OR ".join(["LOWER(content) LIKE ?" for _ in words])
        like_params: List[Any] = [f"%{w}%" for w in words]
        # Récupérer plus de candidats pour re-trier localement
        like_params.append(top_k * 4)

        cursor = await conn.execute(
            f"""SELECT id, node_type, content, confidence, created_at, updated_at,
                       access_count, decay_rate, source
                FROM context_nodes
                WHERE archived=0 AND ({conditions})
                ORDER BY confidence DESC, access_count DESC
                LIMIT ?""",
            like_params,
        )
        rows = await cursor.fetchall()

        # Re-trier par score = nb_mots_correspondants × confidence
        def relevance(row: Any) -> float:
            c = row["content"].lower()
            matches = sum(1 for w in words if w in c)
            return matches * row["confidence"]

        sorted_rows = sorted(rows, key=relevance, reverse=True)
        return [self._row_to_node(r) for r in sorted_rows[:top_k]]

    async def reinforce(self, node_id: str) -> None:
        """
        LTP : augmente la confiance d'un nœud accédé.

        Args:
            node_id: ID du nœud à renforcer.
        """
        conn = await self._get_conn()
        now = time.time()
        await conn.execute(
            """UPDATE context_nodes
               SET confidence    = MIN(1.0, confidence + ?),
                   access_count  = access_count + 1,
                   updated_at    = ?
               WHERE id=? AND archived=0""",
            (LTP_BOOST, now, node_id),
        )
        await conn.commit()

    async def decay(self) -> int:
        """
        LTD : réduit la confiance des nœuds non accédés, puis archive
        ceux dont la confiance tombe sous ARCHIVE_THRESHOLD.

        Le déclin est proportionnel au temps écoulé depuis le dernier accès
        et au taux decay_rate du nœud (en heures).

        Returns:
            Nombre de nœuds archivés lors de cet appel.
        """
        conn = await self._get_conn()
        now = time.time()

        # Appliquer le déclin temporel
        await conn.execute(
            """UPDATE context_nodes
               SET confidence = MAX(0.0,
                   confidence - (decay_rate * (? - updated_at) / 3600.0)),
                   updated_at = ?
               WHERE archived=0""",
            (now, now),
        )

        # Compter les nœuds à archiver
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
            logger.info(f"ContextGraph: {archived_count} nœud(s) archivé(s) (LTD)")

        await conn.commit()
        return archived_count

    async def get_user_profile(self) -> Dict[str, Any]:
        """
        Retourne un résumé structuré du profil utilisateur.

        Les nœuds sont groupés par type et triés par confiance décroissante.

        Returns:
            Dict avec clés = node_type + "_stats" pour les statistiques globales.
        """
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT id, node_type, content, confidence, created_at, updated_at,
                      access_count, decay_rate, source
               FROM context_nodes
               WHERE archived=0
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
            })

        total = sum(len(v) for v in profile.values())
        profile["_stats"] = {
            "total_nodes": total,
            "generated_at": datetime.fromtimestamp(time.time()).isoformat(),
        }

        return profile

    async def get_context_for(self, task_description: str, top_k: int = 5) -> str:
        """
        Retourne le contexte pertinent pour une tâche donnée, formaté en texte.

        Args:
            task_description: Description de la tâche à réaliser.
            top_k: Nombre de nœuds à inclure dans le contexte.

        Returns:
            Contexte formaté (chaîne vide si aucun nœud pertinent).
        """
        nodes = await self.query(task_description, top_k=top_k)
        if not nodes:
            return ""

        parts: List[str] = []
        for node in nodes:
            if node.confidence > 0.7:
                conf_label = "haute"
            elif node.confidence > 0.4:
                conf_label = "moyenne"
            else:
                conf_label = "faible"
            parts.append(
                f"[{node.node_type.upper()}] {node.content} "
                f"(confiance {conf_label}: {node.confidence:.2f})"
            )

        return "\n".join(parts)

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
    ) -> None:
        """
        Ajoute ou met à jour une relation entre deux nœuds.

        Args:
            source_id: ID du nœud source.
            target_id: ID du nœud cible.
            relation: Type de relation (parmi EDGE_RELATIONS).
            weight: Poids de la relation.
        """
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

    async def get_edges(self, node_id: str) -> List[ContextEdge]:
        """
        Retourne toutes les arêtes d'un nœud (entrantes et sortantes).

        Args:
            node_id: ID du nœud.

        Returns:
            Liste de ContextEdge.
        """
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT source_id, target_id, relation, weight
               FROM context_edges
               WHERE source_id=? OR target_id=?""",
            (node_id, node_id),
        )
        rows = await cursor.fetchall()
        return [
            ContextEdge(
                source_id=row["source_id"],
                target_id=row["target_id"],
                relation=row["relation"],
                weight=row["weight"],
            )
            for row in rows
        ]

    async def _publish_update(self, event_type: str, node_id: str) -> None:
        """Publie une mise à jour sur l'EventBus si disponible."""
        event_bus = self._event_bus
        token = self._token
        if event_bus is None or token is None:
            return
        try:
            await event_bus.publish(
                channel="context_update",
                data={"event_type": event_type, "node_id": node_id},
                source=self._source,
                token=token,
            )
        except Exception as e:
            logger.debug(f"ContextGraph: publication EventBus échouée: {e}")

    async def close(self) -> None:
        """Ferme proprement la connexion SQLite."""
        conn = self._conn
        if conn is not None:
            await conn.close()
            self._conn = None

    async def __aenter__(self) -> "ContextGraph":
        await self._get_conn()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
