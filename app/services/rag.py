"""
Service de RAG (Retrieval-Augmented Generation) utilisant FAISS pour la recherche
et SQLite pour stocker les métadonnées des chunks.
Utilise OllamaEmbedder (mxbai-embed-large) pour les embeddings — pas de sentence-transformers.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
import pymupdf  # fitz

from ..utils.exceptions import IndexingError
from ..utils.logger import get_logger

logger = get_logger(__name__)


class RAGService:
    """
    Service de RAG utilisant FAISS et SQLite avec embeddings via Ollama.
    Stocke aussi les conversations (mémoire épisodique vectorielle).
    """

    def __init__(self, config: Any, embedder: Optional[Any] = None) -> None:
        """
        Args:
            config: RAGConfig dataclass.
            embedder: OllamaEmbedder instance (si None, créé automatiquement).
        """
        self.config = config
        self.data_dir = Path("./rag_data")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Embedder
        self.embedder = embedder
        self.active = embedder is not None

        if self.active and self.embedder is not None:
            self.dimension = self.embedder.get_sentence_embedding_dimension()
            logger.info(f"✅ RAG actif avec OllamaEmbedder (dim={self.dimension})")
        else:
            self.dimension = 1024
            logger.info("RAG en mode passif (embedder sera injecté plus tard)")

        # Paramètres
        self.chunk_size = config.chunk_size
        self.chunk_overlap = config.chunk_overlap
        self.max_sources = getattr(config, "max_sources", 3)

        # Initialisation FAISS + SQLite
        self._init_faiss()
        self._init_sqlite()

    def set_embedder(self, embedder: Any) -> None:
        """Injecte l'embedder après construction (pour éviter les dépendances circulaires)."""
        self.embedder = embedder
        self.active = True
        old_dim = self.dimension
        self.dimension = embedder.get_sentence_embedding_dimension()
        if old_dim != self.dimension:
            # Recréer l'index FAISS avec la bonne dimension
            self.index = faiss.IndexFlatL2(self.dimension)
            self.id_mapping = []
            logger.info(f"Index FAISS recréé (dim {old_dim} → {self.dimension})")
        logger.info(f"✅ RAG activé avec embedder (dim={self.dimension})")

    def _init_faiss(self) -> None:
        """Initialise ou charge l'index FAISS."""
        self.index_path = self.data_dir / "faiss.index"
        if self.index_path.exists():
            try:
                self.index = faiss.read_index(str(self.index_path))
                if self.index.d != self.dimension:
                    logger.warning(
                        f"Dimension FAISS ({self.index.d}) != embedder ({self.dimension}), "
                        f"recréation de l'index"
                    )
                    self.index = faiss.IndexFlatL2(self.dimension)
                else:
                    logger.info(f"Index FAISS chargé ({self.index.ntotal} vecteurs)")
            except Exception as e:
                logger.warning(f"Erreur chargement index FAISS: {e}, recréation")
                self.index = faiss.IndexFlatL2(self.dimension)
        else:
            self.index = faiss.IndexFlatL2(self.dimension)
            logger.info("Nouvel index FAISS créé")

        # Mapping positions FAISS → IDs chunks
        self.mapping_path = self.data_dir / "id_mapping.json"
        if self.mapping_path.exists():
            try:
                self.id_mapping: List[int] = json.loads(self.mapping_path.read_text())
            except Exception:
                self.id_mapping = []
        else:
            self.id_mapping = []

    def _init_sqlite(self) -> None:
        """Initialise la base SQLite pour les métadonnées."""
        self.db_path = self.data_dir / "metadata.db"
        self.conn = sqlite3.connect(str(self.db_path))
        # Optimisations WAL : meilleures perfs en lecture/écriture concurrentes
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-64000")  # 64 Mo de cache pages
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL,
                hash TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        # Table pour les conversations indexées
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                query TEXT NOT NULL,
                response TEXT NOT NULL
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_ts ON conversations(timestamp)"
        )
        self.conn.commit()

    def _save_mapping(self) -> None:
        """Sauvegarde le mapping FAISS → IDs en JSON (pas pickle)."""
        self.mapping_path.write_text(json.dumps(self.id_mapping))

    # -----------------------------------------------------------------------
    # Indexation de conversations (mémoire épisodique vectorielle)
    # -----------------------------------------------------------------------
    def index_conversation(self, query: str, response: str, timestamp: float) -> bool:
        """
        Indexe une conversation (query+response) dans FAISS pour la recherche sémantique.

        Args:
            query: Requête utilisateur.
            response: Réponse de l'assistant.
            timestamp: Timestamp de la conversation.

        Returns:
            True si indexé avec succès.
        """
        embedder = self.embedder
        if not self.active or embedder is None:
            return False

        try:
            # Combiner query et response pour l'embedding
            text = f"Question: {query}\nRéponse: {response}"
            embedding = embedder.encode(text)

            # Insérer dans SQLite
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO conversations (timestamp, query, response) VALUES (?, ?, ?)",
                (timestamp, query, response),
            )
            conv_id: int = cur.lastrowid or 0

            # Ajouter à FAISS (ID négatif pour distinguer des chunks de fichiers)
            self.index.add(np.array([embedding]).astype("float32"))  # type: ignore[arg-type]
            self.id_mapping.append(-conv_id)  # négatif = conversation

            self.conn.commit()
            faiss.write_index(self.index, str(self.index_path))
            self._save_mapping()

            logger.debug(f"💾 Conversation indexée (id={conv_id})")
            return True
        except Exception as e:
            logger.error(f"Erreur indexation conversation: {e}")
            return False

    def search_memories(self, query: str, n_results: int = 3) -> List[Dict[str, Any]]:
        """
        Recherche les souvenirs (conversations passées) les plus pertinents.

        Args:
            query: Requête de recherche.
            n_results: Nombre de résultats max.

        Returns:
            Liste de dicts avec keys: query, response, similarity, source.
        """
        embedder = self.embedder
        if not self.active or embedder is None or self.index.ntotal == 0:
            return []

        try:
            q_emb = embedder.encode([query]).astype("float32")
        except Exception as e:
            logger.error(f"Erreur d'encodage: {e}")
            return []

        n = min(n_results, self.index.ntotal)
        distances, indices = self.index.search(q_emb, n)  # type: ignore[call-arg]

        results: List[Dict[str, Any]] = []
        for i, idx in enumerate(indices[0]):
            if idx == -1 or idx >= len(self.id_mapping):
                continue

            mapping_id = self.id_mapping[idx]
            distance = float(distances[0][i])
            # Convertir distance L2 en score de similarité (0-1)
            similarity = 1.0 / (1.0 + distance)

            if mapping_id < 0:
                # Conversation
                conv_id = -mapping_id
                cur = self.conn.execute(
                    "SELECT query, response FROM conversations WHERE id=?",
                    (conv_id,),
                )
                row = cur.fetchone()
                if row:
                    results.append({
                        "query": row[0],
                        "response": row[1],
                        "similarity": similarity,
                        "source": "conversation",
                    })
            else:
                # Chunk de fichier
                cur = self.conn.execute(
                    "SELECT content, source FROM chunks WHERE id=?",
                    (mapping_id,),
                )
                row = cur.fetchone()
                if row:
                    results.append({
                        "query": "",
                        "response": row[0],
                        "similarity": similarity,
                        "source": Path(row[1]).name,
                    })

        return results

    # -----------------------------------------------------------------------
    # Indexation de fichiers (inchangée dans la logique)
    # -----------------------------------------------------------------------
    def _get_file_hash(self, path: Path) -> str:
        """Calcule le hash MD5 d'un fichier."""
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _chunk_text(self, text: str) -> List[str]:
        """Découpe un texte en chunks de taille chunk_size avec overlap."""
        words = text.split()
        if len(words) <= self.chunk_size:
            return [text]
        step = self.chunk_size - self.chunk_overlap
        chunks = []
        for i in range(0, len(words), step):
            chunk = " ".join(words[i: i + self.chunk_size])
            chunks.append(chunk)
        return chunks

    def _read_pdf(self, path: Path) -> str:
        """Lit le contenu texte d'un PDF."""
        try:
            doc = pymupdf.open(path)
            text = ""
            for page in doc:
                text += str(page.get_text())
            return text
        except Exception as e:
            raise IndexingError(f"Erreur lecture PDF {path}: {e}")

    def _read_text(self, path: Path) -> str:
        """Lit un fichier texte avec gestion multi-encodage."""
        encodings = ["utf-8", "latin-1", "cp1252"]
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise IndexingError(
            f"Impossible de lire le fichier {path} avec les encodages essayés"
        )

    def index_file(self, path: str) -> bool:
        """Indexe un fichier (PDF ou texte) dans la base RAG."""
        if not self.active:
            logger.debug("RAG inactif : indexation ignorée")
            return False

        file_path = Path(path)
        if not file_path.exists():
            raise IndexingError(f"Fichier introuvable: {file_path}")

        file_hash = self._get_file_hash(file_path)

        cur = self.conn.execute(
            "SELECT id FROM chunks WHERE source=? AND hash=? LIMIT 1",
            (str(file_path), file_hash),
        )
        if cur.fetchone():
            logger.info(f"Fichier déjà indexé et inchangé: {file_path}")
            return True

        self.conn.execute("DELETE FROM chunks WHERE source=?", (str(file_path),))
        self.conn.commit()

        if file_path.suffix.lower() == ".pdf":
            text = self._read_pdf(file_path)
        else:
            text = self._read_text(file_path)

        if not text.strip():
            logger.warning(f"Fichier vide ou illisible: {file_path}")
            return False

        chunks = self._chunk_text(text)

        embedder = self.embedder
        if embedder is None:
            return False

        try:
            embeddings = embedder.encode(chunks, show_progress_bar=False)
        except Exception as e:
            raise IndexingError(f"Erreur lors du calcul des embeddings: {e}")

        cur = self.conn.cursor()
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            cur.execute(
                "INSERT INTO chunks (source, chunk_index, total_chunks, hash, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(file_path), i, len(chunks), file_hash, chunk),
            )
            chunk_id: int = cur.lastrowid or 0
            self.index.add(np.array([emb]).astype("float32"))  # type: ignore[arg-type]
            self.id_mapping.append(chunk_id)

        self.conn.commit()
        faiss.write_index(self.index, str(self.index_path))
        self._save_mapping()

        logger.info(f"✅ Indexé: {file_path} ({len(chunks)} chunks)")
        return True

    def index_folder(self, path: str) -> int:
        """Indexe récursivement tous les fichiers supportés dans un dossier."""
        if not self.active:
            return 0

        folder_path = Path(path)
        if not folder_path.is_dir():
            raise IndexingError(f"Dossier invalide: {folder_path}")

        extensions = {".pdf", ".txt", ".md", ".py", ".rst", ".csv", ".json", ".xml"}
        count = 0
        for file_path in folder_path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in extensions:
                try:
                    if self.index_file(str(file_path)):
                        count += 1
                except Exception as e:
                    logger.error(f"Erreur indexation {file_path}: {e}")
        logger.info(f"✅ {count} fichiers indexés dans {folder_path}")
        return count

    def query(self, question: str, n_results: Optional[int] = None) -> str:
        """
        Recherche les chunks/conversations les plus pertinents pour une question.
        Retourne le contexte formaté ou une chaîne vide.
        """
        if not self.active:
            return ""

        memories = self.search_memories(question, n_results or self.max_sources)
        if not memories:
            return ""

        parts = []
        for mem in memories:
            if mem["source"] == "conversation":
                parts.append(
                    f"[Souvenir] Q: {mem['query']}\nR: {mem['response']}"
                )
            else:
                parts.append(f"[Source: {mem['source']}]\n{mem['response']}")

        return "\n\n".join(parts)

    def clear(self, source: Optional[str] = None) -> None:
        """Supprime tous les index ou seulement ceux d'une source spécifique."""
        if source:
            self.conn.execute("DELETE FROM chunks WHERE source=?", (source,))
            self.conn.commit()
            self._rebuild_faiss()
            logger.info(f"Index supprimé pour {source}")
        else:
            self.conn.execute("DELETE FROM chunks")
            self.conn.execute("DELETE FROM conversations")
            self.conn.commit()
            self.index = faiss.IndexFlatL2(self.dimension)
            self.id_mapping = []
            faiss.write_index(self.index, str(self.index_path))
            self._save_mapping()
            logger.info("Tous les index supprimés")

    def _rebuild_faiss(self) -> None:
        """Reconstruit l'index FAISS à partir de la base SQLite."""
        if not self.active:
            return

        # Récupérer tous les chunks
        cur = self.conn.execute("SELECT id, content FROM chunks ORDER BY id")
        chunk_rows = cur.fetchall()

        # Récupérer toutes les conversations
        cur = self.conn.execute(
            "SELECT id, query, response FROM conversations ORDER BY id"
        )
        conv_rows = cur.fetchall()

        all_texts = []
        all_ids = []

        for row in chunk_rows:
            all_texts.append(row[1])
            all_ids.append(row[0])  # positif = chunk

        for row in conv_rows:
            all_texts.append(f"Question: {row[1]}\nRéponse: {row[2]}")
            all_ids.append(-row[0])  # négatif = conversation

        embedder = self.embedder
        if not all_texts or embedder is None:
            self.index = faiss.IndexFlatL2(self.dimension)
            self.id_mapping = []
        else:
            logger.info(f"Reconstruction index FAISS ({len(all_texts)} entrées)...")
            embeddings = embedder.encode(all_texts)
            self.index = faiss.IndexFlatL2(self.dimension)
            self.index.add(embeddings.astype("float32"))  # type: ignore[arg-type]
            self.id_mapping = all_ids

        faiss.write_index(self.index, str(self.index_path))
        self._save_mapping()
