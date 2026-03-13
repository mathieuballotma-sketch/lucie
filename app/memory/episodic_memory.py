"""
Mémoire épisodique - Stockage à long terme des interactions.
Version asynchrone avec aiosqlite, robustesse accrue, métriques,
et préparation pour la recherche sémantique par embeddings.
Incarne les principes :
- Homéostasie : gestion d'erreurs, reprise sur panne.
- Évolution : métriques, extensibilité vers la recherche sémantique.
- Entropie : code clair, documentation, suppression des doublons.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import aiosqlite

from app.utils.logger import logger


# -----------------------------------------------------------------------
# Exceptions personnalisées
# -----------------------------------------------------------------------
class MemoryError(Exception):
    """Erreur de base pour la mémoire épisodique."""
    pass


class MemoryStorageError(MemoryError):
    """Erreur lors d'une opération de stockage."""
    pass


class MemoryRetrievalError(MemoryError):
    """Erreur lors de la récupération d'épisodes."""
    pass


# -----------------------------------------------------------------------
# Classe principale
# -----------------------------------------------------------------------
class EpisodicMemory:
    """
    Stockage à long terme des épisodes (requêtes/réponses) dans une base SQLite.
    Utilise aiosqlite pour les opérations asynchrones.

    Peut être étendu pour la recherche sémantique en fournissant une fonction d'embedding.
    """

    def __init__(
        self,
        persist_directory: str,
        max_entries: int = 10000,
        metrics_collector: Optional[Any] = None,
        embedding_fn: Optional[Callable[[str], List[float]]] = None,
    ):
        """
        Args:
            persist_directory: dossier où stocker la base de données
            max_entries: nombre maximum d'entrées avant nettoyage
            metrics_collector: collecteur de métriques (optionnel)
            embedding_fn: fonction qui transforme une requête en vecteur d'embedding
                          (si fournie, active la recherche sémantique)
        """
        self.db_path = Path(persist_directory) / "episodic.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self.metrics = metrics_collector
        self.embedding_fn = embedding_fn
        self._connection: Optional[aiosqlite.Connection] = None

    async def _get_connection(self) -> aiosqlite.Connection:
        """Retourne une connexion à la base, en la créant si nécessaire."""
        if self._connection is None:
            try:
                self._connection = await aiosqlite.connect(str(self.db_path))
                await self._connection.execute("PRAGMA foreign_keys = ON")
                # Table principale
                await self._connection.execute("""
                    CREATE TABLE IF NOT EXISTS episodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        query TEXT NOT NULL,
                        response TEXT NOT NULL,
                        metadata TEXT
                    )
                """)
                # Table pour les embeddings (optionnelle)
                if self.embedding_fn:
                    await self._connection.execute("""
                        CREATE TABLE IF NOT EXISTS embeddings (
                            episode_id INTEGER PRIMARY KEY,
                            vector BLOB NOT NULL,
                            FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
                        )
                    """)
                await self._connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_timestamp ON episodes(timestamp)"
                )
                await self._connection.commit()
            except aiosqlite.Error as e:
                logger.error(f"Erreur lors de l'initialisation de la base: {e}")
                raise MemoryStorageError(f"Impossible d'initialiser la base: {e}") from e
        return self._connection

    async def add_episode(
        self,
        query: str,
        response: str,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Ajoute un épisode à la mémoire.

        Args:
            query: requête utilisateur
            response: réponse de l'assistant
            metadata: métadonnées additionnelles (ex: durée, agent utilisé)

        Raises:
            MemoryStorageError: si l'insertion échoue
        """
        start = time.time()
        conn = await self._get_connection()
        try:
            cursor = await conn.execute(
                "INSERT INTO episodes (timestamp, query, response, metadata) VALUES (?, ?, ?, ?)",
                (time.time(), query, response, json.dumps(metadata or {}))
            )
            episode_id = cursor.lastrowid

            # Si une fonction d'embedding est fournie, calculer et stocker le vecteur
            if self.embedding_fn:
                try:
                    embedding = self.embedding_fn(query)
                    # Convertir en bytes pour stockage (ex: avec pickle ou json)
                    # On utilise json.dumps pour rester lisible, mais c'est moins efficace.
                    # Pour la performance, on pourrait utiliser numpy et tobytes().
                    import numpy as np
                    vector_bytes = np.array(embedding, dtype=np.float32).tobytes()
                    await conn.execute(
                        "INSERT INTO embeddings (episode_id, vector) VALUES (?, ?)",
                        (episode_id, vector_bytes)
                    )
                except Exception as e:
                    logger.error(f"Erreur lors du calcul/stockage de l'embedding: {e}")
                    # On ne bloque pas l'insertion principale

            await conn.commit()
            self.metrics.record_timing("episodic.add_duration", time.time() - start)
        except aiosqlite.Error as e:
            logger.error(f"Erreur lors de l'ajout de l'épisode: {e}")
            raise MemoryStorageError(f"Échec de l'ajout de l'épisode: {e}") from e

        # Nettoyage asynchrone (ne pas attendre)
        asyncio.create_task(self._cleanup())

    async def _cleanup(self) -> None:
        """
        Supprime les entrées les plus anciennes si le nombre maximum est dépassé.
        Méthode plus efficace : on récupère le timestamp de la (max_entries)ème entrée
        et on supprime tout ce qui est plus vieux.
        """
        try:
            conn = await self._get_connection()
            cursor = await conn.execute("SELECT COUNT(*) FROM episodes")
            count = (await cursor.fetchone())[0]
            if count > self.max_entries:
                # Récupérer le timestamp de la (max_entries)ème entrée la plus récente
                offset = self.max_entries
                cursor = await conn.execute(
                    "SELECT timestamp FROM episodes ORDER BY timestamp DESC LIMIT 1 OFFSET ?",
                    (offset,)
                )
                row = await cursor.fetchone()
                if row:
                    threshold = row[0]
                    await conn.execute(
                        "DELETE FROM episodes WHERE timestamp < ?",
                        (threshold,)
                    )
                    await conn.commit()
                    deleted = count - self.max_entries
                    logger.debug(f"Nettoyage de la mémoire épisodique: {deleted} entrées supprimées")
                    self.metrics.record_value("episodic.cleanup_deleted", deleted)
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage de la mémoire: {e}")

    async def remember(
        self,
        query: str,
        n_results: int = 5,
        min_similarity: float = 0.0,
        use_semantic: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Récupère les épisodes les plus pertinents pour une requête.

        Args:
            query: requête de recherche
            n_results: nombre maximum de résultats
            min_similarity: seuil de similarité minimum (non utilisé actuellement)
            use_semantic: si True et que embedding_fn est disponible, utilise la recherche sémantique

        Returns:
            Liste d'épisodes, chacun avec les clés : query, response, metadata, timestamp, similarity

        Raises:
            MemoryRetrievalError: si la récupération échoue
        """
        start = time.time()
        try:
            if use_semantic and self.embedding_fn:
                results = await self._similarity_search(query, n_results, min_similarity)
            else:
                results = await self._chronological_search(n_results)
            self.metrics.record_timing("episodic.remember_duration", time.time() - start)
            return results
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des épisodes: {e}")
            raise MemoryRetrievalError(f"Échec de la récupération: {e}") from e

    async def _chronological_search(self, n_results: int) -> List[Dict[str, Any]]:
        """Recherche chronologique simple (les plus récents)."""
        conn = await self._get_connection()
        cursor = await conn.execute(
            "SELECT query, response, metadata, timestamp FROM episodes ORDER BY timestamp DESC LIMIT ?",
            (n_results,)
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            query_text, response_text, metadata_json, ts = row
            results.append({
                "query": query_text,
                "response": response_text,
                "metadata": json.loads(metadata_json),
                "timestamp": ts,
                "similarity": 1.0  # factice
            })
        return results

    async def _similarity_search(
        self,
        query: str,
        n_results: int,
        min_similarity: float
    ) -> List[Dict[str, Any]]:
        """
        Recherche par similarité cosinus entre l'embedding de la requête
        et ceux stockés en base.
        Nécessite que embedding_fn soit fourni et que la table embeddings existe.
        """
        if not self.embedding_fn:
            return await self._chronological_search(n_results)

        # Calculer l'embedding de la requête
        query_emb = self.embedding_fn(query)
        import numpy as np
        query_vec = np.array(query_emb, dtype=np.float32)

        conn = await self._get_connection()
        # Récupérer tous les embeddings (attention : peut être lourd, à optimiser avec une vraie base vectorielle)
        cursor = await conn.execute("""
            SELECT e.id, e.query, e.response, e.metadata, e.timestamp, emb.vector
            FROM episodes e
            JOIN embeddings emb ON e.id = emb.episode_id
        """)
        rows = await cursor.fetchall()

        similarities = []
        for row in rows:
            ep_id, q_text, r_text, meta_json, ts, vec_bytes = row
            vec = np.frombuffer(vec_bytes, dtype=np.float32)
            # Normalisation (si les embeddings ne sont pas normalisés)
            norm_q = np.linalg.norm(query_vec)
            norm_v = np.linalg.norm(vec)
            if norm_q == 0 or norm_v == 0:
                sim = 0.0
            else:
                sim = np.dot(query_vec, vec) / (norm_q * norm_v)
            if sim >= min_similarity:
                similarities.append((sim, {
                    "query": q_text,
                    "response": r_text,
                    "metadata": json.loads(meta_json),
                    "timestamp": ts,
                    "similarity": float(sim)
                }))

        # Trier par similarité décroissante
        similarities.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in similarities[:n_results]]

    # Méthode de compatibilité pour l'ancien code qui utilise search()
    async def search(
        self,
        query: str,
        n_results: int = 5,
        min_similarity: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Ancien nom pour remember. Redirige vers remember avec un avertissement.
        """
        logger.warning("search() est déprécié, utilisez remember() à la place.")
        return await self.remember(query, n_results, min_similarity)

    async def close(self) -> None:
        """Ferme la connexion à la base de données."""
        if self._connection:
            try:
                await self._connection.close()
            except aiosqlite.Error as e:
                logger.error(f"Erreur lors de la fermeture de la connexion: {e}")
            finally:
                self._connection = None
                logger.debug("Connexion à la mémoire épisodique fermée")

    async def __aenter__(self):
        await self._get_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()