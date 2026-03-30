"""
SagaOrchestrator — workflow transactionnel avec reprise après crash.

Implémente le pattern Saga (orchestration) pour les workflows multi-étapes
nécessitant une durabilité et une compensation en cas d'échec.

Chaque étape peut être :
  - idempotente (safe to replay) → reprise directe en cas de crash
  - non-idempotente → compensation (rollback) si interrompue

Composants :
  - SagaStep       : Définition d'une étape (action + compensation)
  - SagaDefinition : Ensemble ordonné d'étapes formant un workflow
  - StepRecord     : Enregistrement de l'exécution d'une étape (persisté)
  - SagaRecord     : Enregistrement d'une instance de saga (persisté)
  - SagaStore      : Persistance SQLite avec WAL + SYNCHRONOUS=FULL
  - ObjectStore    : Stockage externe des gros objets (SHA-256, déduplication, TTL 7j)
  - SagaOrchestrator : Exécute, reprend et compense les sagas

Exceptions métier :
  - ContextTooLargeError : contexte > 10 Mo
  - DiskFullError        : espace disque insuffisant
"""

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

SAGAS_DB_PATH: Path   = Path.home() / ".lucie" / "sagas.db"
OBJECTS_DIR: Path     = Path.home() / ".lucie" / "objects"

MAX_CONTEXT_BYTES: int = 10 * 1024 * 1024   # 10 Mo
HEARTBEAT_INTERVAL_S: float = 10.0
HEARTBEAT_TIMEOUT_S:  float = 60.0
OBJECT_TTL_DAYS: int  = 7


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions métier
# ─────────────────────────────────────────────────────────────────────────────

class ContextTooLargeError(Exception):
    """Levée si le contexte de saga dépasse 10 Mo."""
    pass


class DiskFullError(Exception):
    """Levée si l'espace disque est insuffisant pour persister une saga."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# États
# ─────────────────────────────────────────────────────────────────────────────

class SagaStatus(str, Enum):
    PENDING       = "PENDING"
    RUNNING       = "RUNNING"
    COMPENSATING  = "COMPENSATING"
    COMPLETED     = "COMPLETED"
    COMPENSATED   = "COMPENSATED"
    FAILED        = "FAILED"


class StepStatus(str, Enum):
    PENDING       = "PENDING"
    RUNNING       = "RUNNING"
    COMPLETED     = "COMPLETED"
    COMPENSATING  = "COMPENSATING"
    COMPENSATED   = "COMPENSATED"
    FAILED        = "FAILED"


# ─────────────────────────────────────────────────────────────────────────────
# Références vers les gros objets
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StoredObjectRef:
    """
    Référence vers un objet stocké dans l'ObjectStore.
    Permet de ne pas mettre de gros objets (données binaires, résultats volumineux)
    directement dans le contexte SQLite.
    """
    sha256: str
    size_bytes: int
    content_type: str = "application/octet-stream"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "_type": "StoredObjectRef",
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoredObjectRef":
        return cls(
            sha256=data["sha256"],
            size_bytes=data["size_bytes"],
            content_type=data.get("content_type", "application/octet-stream"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# ObjectStore — stockage déduplication SHA-256
# ─────────────────────────────────────────────────────────────────────────────

class ObjectStore:
    """
    Stockage de gros objets par empreinte SHA-256.

    - Déduplication : si deux sagas stockent le même contenu, un seul fichier.
    - TTL automatique : les objets non référencés depuis 7 jours sont purgés.
    - Structure : ~/.lucie/objects/<sha256[:2]>/<sha256>.bin
    """

    def __init__(self, base_dir: Path = OBJECTS_DIR) -> None:
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)
        logger.debug(f"ObjectStore initialisé dans {base_dir}")

    def _path_for(self, sha256: str) -> Path:
        return self._base / sha256[:2] / f"{sha256}.bin"

    def store(self, data: bytes) -> StoredObjectRef:
        """
        Stocke les données et retourne une référence.
        Idempotent : si le contenu existe déjà, retourne simplement la référence.

        Raises:
            DiskFullError: si l'espace disque est insuffisant.
        """
        sha256 = hashlib.sha256(data).hexdigest()
        path = self._path_for(sha256)

        if path.exists():
            return StoredObjectRef(sha256=sha256, size_bytes=len(data))

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Vérification espace disque avant écriture
            free = shutil.disk_usage(path.parent).free
            if free < len(data) + 1024 * 1024:  # Marge de 1 Mo
                raise DiskFullError(
                    f"Espace disque insuffisant : {free} octets libres, "
                    f"{len(data)} nécessaires"
                )
            path.write_bytes(data)
        except DiskFullError:
            raise
        except OSError as e:
            if e.errno == 28:  # ENOSPC
                raise DiskFullError(f"Disque plein (ENOSPC): {e}") from e
            raise

        logger.debug(f"ObjectStore : objet stocké {sha256[:12]}… ({len(data)} octets)")
        return StoredObjectRef(sha256=sha256, size_bytes=len(data))

    def retrieve(self, ref: StoredObjectRef) -> bytes:
        """Récupère les données d'un objet par sa référence."""
        path = self._path_for(ref.sha256)
        if not path.exists():
            raise FileNotFoundError(f"Objet introuvable : {ref.sha256}")
        return path.read_bytes()

    def cleanup(self, max_age_days: int = OBJECT_TTL_DAYS) -> int:
        """
        Supprime les fichiers plus vieux que max_age_days.
        Retourne le nombre d'objets supprimés.
        """
        cutoff = time.time() - max_age_days * 86_400
        removed = 0
        for path in self._base.rglob("*.bin"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        if removed:
            logger.info(f"ObjectStore : {removed} objet(s) purgé(s) (TTL {max_age_days}j)")
        return removed


# ─────────────────────────────────────────────────────────────────────────────
# Définitions des sagas
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SagaStep:
    """
    Définition d'une étape de saga.

    Args:
        name:        Identifiant unique de l'étape au sein de la saga.
        action:      Coroutine exécutant l'étape. Reçoit le contexte courant.
        compensate:  Coroutine de compensation (rollback). Reçoit le contexte.
        idempotent:  Si True, l'étape peut être rejouée sans risque.
        timeout:     Timeout en secondes pour l'exécution de l'étape.
    """
    name: str
    action: Callable[[Dict[str, Any]], Any]
    compensate: Callable[[Dict[str, Any]], Any]
    idempotent: bool = False
    timeout: float = 30.0


@dataclass
class SagaDefinition:
    """Définition complète d'un workflow saga."""
    name: str
    steps: List[SagaStep]
    version: int = 1


# ─────────────────────────────────────────────────────────────────────────────
# Enregistrements persistés
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StepRecord:
    """Enregistrement de l'exécution d'une étape (persisté en SQLite)."""
    saga_id: str
    step_name: str
    status: StepStatus
    result: Optional[str] = None       # JSON sérialisé du résultat
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


@dataclass
class SagaRecord:
    """Enregistrement d'une instance de saga (persisté en SQLite)."""
    id: str
    definition_name: str
    status: SagaStatus
    context: Dict[str, Any]            # Contexte courant (< 10 Mo)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    heartbeat_at: float = field(default_factory=time.time)
    current_step: Optional[str] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# SagaStore — persistance SQLite
# ─────────────────────────────────────────────────────────────────────────────

class SagaStore:
    """
    Persistance des sagas et étapes dans SQLite.

    Configuration durabilité maximale :
    - journal_mode=WAL   : lectures non bloquées par les écritures
    - synchronous=FULL   : fsync à chaque commit (résistance aux crashes)

    Thread-safe via threading.Lock.
    """

    def __init__(self, db_path: Path = SAGAS_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._init_db()
        logger.info(f"SagaStore initialisé ({db_path})")

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sagas (
                id              TEXT PRIMARY KEY,
                definition_name TEXT NOT NULL,
                status          TEXT NOT NULL,
                context         TEXT NOT NULL,
                current_step    TEXT,
                error           TEXT,
                created_at      REAL NOT NULL,
                updated_at      REAL NOT NULL,
                heartbeat_at    REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS steps (
                saga_id       TEXT NOT NULL,
                step_name     TEXT NOT NULL,
                status        TEXT NOT NULL,
                result        TEXT,
                error         TEXT,
                started_at    REAL NOT NULL,
                completed_at  REAL,
                PRIMARY KEY (saga_id, step_name),
                FOREIGN KEY (saga_id) REFERENCES sagas(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sagas_status
                ON sagas(status);
            CREATE INDEX IF NOT EXISTS idx_sagas_heartbeat
                ON sagas(heartbeat_at);
        """)
        self._conn.commit()

    # ── Sagas ──────────────────────────────────────────────────────────────

    def upsert_saga(self, record: SagaRecord) -> None:
        """Insère ou met à jour un enregistrement de saga."""
        ctx_json = json.dumps(record.context)
        if len(ctx_json.encode()) > MAX_CONTEXT_BYTES:
            raise ContextTooLargeError(
                f"Contexte de saga {record.id!r} dépasse 10 Mo "
                f"({len(ctx_json.encode())} octets)"
            )
        with self._lock:
            self._conn.execute("""
                INSERT INTO sagas
                    (id, definition_name, status, context, current_step, error,
                     created_at, updated_at, heartbeat_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status       = excluded.status,
                    context      = excluded.context,
                    current_step = excluded.current_step,
                    error        = excluded.error,
                    updated_at   = excluded.updated_at,
                    heartbeat_at = excluded.heartbeat_at
            """, (
                record.id,
                record.definition_name,
                record.status.value,
                ctx_json,
                record.current_step,
                record.error,
                record.created_at,
                record.updated_at,
                record.heartbeat_at,
            ))
            self._conn.commit()

    def update_heartbeat(self, saga_id: str) -> None:
        """Met à jour le heartbeat d'une saga active."""
        with self._lock:
            self._conn.execute(
                "UPDATE sagas SET heartbeat_at = ? WHERE id = ?",
                (time.time(), saga_id)
            )
            self._conn.commit()

    def get_saga(self, saga_id: str) -> Optional[SagaRecord]:
        """Retourne une saga par son identifiant, ou None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sagas WHERE id = ?", (saga_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_saga(row)

    def get_incomplete_sagas(self) -> List[SagaRecord]:
        """Retourne les sagas RUNNING ou COMPENSATING (non terminées)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sagas WHERE status IN ('RUNNING', 'COMPENSATING')"
            ).fetchall()
        return [self._row_to_saga(r) for r in rows]

    @staticmethod
    def _row_to_saga(row: tuple) -> SagaRecord:
        (saga_id, def_name, status, context, current_step, error,
         created_at, updated_at, heartbeat_at) = row
        return SagaRecord(
            id=saga_id,
            definition_name=def_name,
            status=SagaStatus(status),
            context=json.loads(context),
            current_step=current_step,
            error=error,
            created_at=created_at,
            updated_at=updated_at,
            heartbeat_at=heartbeat_at,
        )

    # ── Étapes ─────────────────────────────────────────────────────────────

    def upsert_step(self, step: StepRecord) -> None:
        """Insère ou met à jour un enregistrement d'étape."""
        with self._lock:
            self._conn.execute("""
                INSERT INTO steps
                    (saga_id, step_name, status, result, error, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(saga_id, step_name) DO UPDATE SET
                    status       = excluded.status,
                    result       = excluded.result,
                    error        = excluded.error,
                    completed_at = excluded.completed_at
            """, (
                step.saga_id,
                step.step_name,
                step.status.value,
                step.result,
                step.error,
                step.started_at,
                step.completed_at,
            ))
            self._conn.commit()

    def get_step(self, saga_id: str, step_name: str) -> Optional[StepRecord]:
        """Retourne un enregistrement d'étape, ou None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steps WHERE saga_id = ? AND step_name = ?",
                (saga_id, step_name)
            ).fetchone()
        if not row:
            return None
        (saga_id_, step_name_, status, result, error, started_at, completed_at) = row
        return StepRecord(
            saga_id=saga_id_,
            step_name=step_name_,
            status=StepStatus(status),
            result=result,
            error=error,
            started_at=started_at,
            completed_at=completed_at,
        )

    def get_steps(self, saga_id: str) -> List[StepRecord]:
        """Retourne tous les enregistrements d'étapes d'une saga."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steps WHERE saga_id = ? ORDER BY started_at",
                (saga_id,)
            ).fetchall()
        result = []
        for row in rows:
            (saga_id_, step_name_, status, res, error, started_at, completed_at) = row
            result.append(StepRecord(
                saga_id=saga_id_,
                step_name=step_name_,
                status=StepStatus(status),
                result=res,
                error=error,
                started_at=started_at,
                completed_at=completed_at,
            ))
        return result


# ─────────────────────────────────────────────────────────────────────────────
# SagaOrchestrator
# ─────────────────────────────────────────────────────────────────────────────

class SagaOrchestrator:
    """
    Orchestre l'exécution des sagas avec durabilité et reprise après crash.

    Fonctionnement :
    - Chaque saga est persistée en SQLite avant et après chaque étape.
    - Un heartbeat toutes les 10 s indique qu'une saga est vivante.
    - Au démarrage, recover_incomplete() reprend les sagas interrompues :
        * RUNNING + étape idempotente → reprendre depuis cette étape
        * RUNNING + étape non-idempotente → démarrer la compensation
        * COMPENSATING → continuer la compensation là où elle s'est arrêtée
        * Heartbeat frais (< 60 s) → ignorer (instance potentiellement vivante)

    Usage :
        orchestrator = SagaOrchestrator()
        await orchestrator.start()
        saga_id = await orchestrator.execute(definition, context)
        await orchestrator.stop()
    """

    def __init__(self,
                 store: Optional[SagaStore] = None,
                 object_store: Optional[ObjectStore] = None) -> None:
        self._store = store or SagaStore()
        self._object_store = object_store or ObjectStore()
        self._definitions: Dict[str, SagaDefinition] = {}
        self._heartbeat_tasks: Dict[str, asyncio.Task[None]] = {}
        self._running: bool = False
        logger.info("✅ SagaOrchestrator initialisé")

    # ─────────────────────────────────────────────────────────────────────────
    # Cycle de vie
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Démarre l'orchestrateur et reprend les sagas incomplètes."""
        self._running = True
        await self.recover_incomplete()
        logger.info("SagaOrchestrator démarré")

    async def stop(self) -> None:
        """Arrête proprement tous les heartbeats."""
        self._running = False
        for task in list(self._heartbeat_tasks.values()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._heartbeat_tasks.clear()
        logger.info("SagaOrchestrator arrêté")

    def register(self, definition: SagaDefinition) -> None:
        """Enregistre une définition de saga pour l'exécution et la reprise."""
        self._definitions[definition.name] = definition
        logger.debug(f"Saga '{definition.name}' enregistrée ({len(definition.steps)} étapes)")

    # ─────────────────────────────────────────────────────────────────────────
    # Exécution
    # ─────────────────────────────────────────────────────────────────────────

    async def execute(self, definition: SagaDefinition, context: Dict[str, Any]) -> str:
        """
        Démarre l'exécution d'une nouvelle saga.

        Args:
            definition: Définition du workflow saga.
            context:    Contexte initial (données d'entrée). Doit faire < 10 Mo.

        Returns:
            Identifiant de la saga créée.

        Raises:
            ContextTooLargeError: Si le contexte dépasse 10 Mo.
            DiskFullError:        Si le disque est plein.
        """
        if not definition.name in self._definitions:
            self.register(definition)

        saga_id = str(uuid.uuid4())
        record = SagaRecord(
            id=saga_id,
            definition_name=definition.name,
            status=SagaStatus.RUNNING,
            context=context,
        )

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._store.upsert_saga, record)
        except ContextTooLargeError:
            raise
        except OSError as e:
            if e.errno == 28:
                raise DiskFullError(f"Disque plein lors de la création de la saga {saga_id}") from e
            raise

        logger.info(f"▶️  Saga {saga_id} ({definition.name}) démarrée")

        # Heartbeat en arrière-plan
        self._heartbeat_tasks[saga_id] = asyncio.create_task(
            self._heartbeat_loop(saga_id), name=f"saga.heartbeat.{saga_id[:8]}"
        )

        try:
            await self._run_steps(record, definition)
        finally:
            # Arrêter le heartbeat
            task = self._heartbeat_tasks.pop(saga_id, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        return saga_id

    async def _run_steps(self, record: SagaRecord, definition: SagaDefinition) -> None:
        """Exécute séquentiellement les étapes d'une saga."""
        loop = asyncio.get_running_loop()
        completed_steps: List[SagaStep] = []

        # Déterminer l'étape de départ (reprise)
        start_index = self._find_start_index(record, definition)

        for i, step in enumerate(definition.steps[start_index:], start=start_index):
            record.current_step = step.name
            record.updated_at = time.time()
            await loop.run_in_executor(None, self._store.upsert_saga, record)

            step_rec = StepRecord(
                saga_id=record.id,
                step_name=step.name,
                status=StepStatus.RUNNING,
            )
            await loop.run_in_executor(None, self._store.upsert_step, step_rec)

            try:
                result = await asyncio.wait_for(
                    step.action(record.context), timeout=step.timeout
                )
                # Mettre à jour le contexte si l'action retourne un dict
                if isinstance(result, dict):
                    record.context.update(result)

                step_rec.status = StepStatus.COMPLETED
                step_rec.result = json.dumps(result) if result is not None else None
                step_rec.completed_at = time.time()
                await loop.run_in_executor(None, self._store.upsert_step, step_rec)
                completed_steps.append(step)
                logger.debug(f"Étape '{step.name}' complétée pour saga {record.id[:8]}…")

            except asyncio.TimeoutError:
                error_msg = f"Timeout ({step.timeout}s) à l'étape '{step.name}'"
                logger.error(f"❌ Saga {record.id[:8]}… : {error_msg}")
                step_rec.status = StepStatus.FAILED
                step_rec.error = error_msg
                step_rec.completed_at = time.time()
                await loop.run_in_executor(None, self._store.upsert_step, step_rec)
                await self._compensate(record, definition, completed_steps)
                return

            except asyncio.CancelledError:
                step_rec.status = StepStatus.FAILED
                step_rec.error = "Annulé"
                step_rec.completed_at = time.time()
                await loop.run_in_executor(None, self._store.upsert_step, step_rec)
                raise

            except Exception as e:
                error_msg = f"Erreur étape '{step.name}': {e}"
                logger.error(f"❌ Saga {record.id[:8]}… : {error_msg}")
                step_rec.status = StepStatus.FAILED
                step_rec.error = error_msg
                step_rec.completed_at = time.time()
                await loop.run_in_executor(None, self._store.upsert_step, step_rec)
                await self._compensate(record, definition, completed_steps)
                return

        # Toutes les étapes complétées
        record.status = SagaStatus.COMPLETED
        record.current_step = None
        record.updated_at = time.time()
        await loop.run_in_executor(None, self._store.upsert_saga, record)
        logger.info(f"✅ Saga {record.id[:8]}… ({definition.name}) complétée")

    def _find_start_index(self, record: SagaRecord, definition: SagaDefinition) -> int:
        """
        Retourne l'index de l'étape à partir de laquelle reprendre.
        Cherche la première étape non encore COMPLETED dans le store.
        """
        if not record.current_step:
            return 0
        loop = asyncio.get_event_loop()
        step_records = {
            sr.step_name: sr
            for sr in self._store.get_steps(record.id)
        }
        for i, step in enumerate(definition.steps):
            sr = step_records.get(step.name)
            if sr is None or sr.status != StepStatus.COMPLETED:
                return i
        return len(definition.steps)

    # ─────────────────────────────────────────────────────────────────────────
    # Compensation (rollback)
    # ─────────────────────────────────────────────────────────────────────────

    async def _compensate(self,
                          record: SagaRecord,
                          definition: SagaDefinition,
                          completed_steps: List[SagaStep]) -> None:
        """
        Exécute la compensation des étapes déjà complétées, en ordre inverse.
        """
        loop = asyncio.get_running_loop()
        record.status = SagaStatus.COMPENSATING
        record.updated_at = time.time()
        await loop.run_in_executor(None, self._store.upsert_saga, record)
        logger.info(f"↩️  Compensation démarrée pour saga {record.id[:8]}…")

        for step in reversed(completed_steps):
            step_rec = self._store.get_step(record.id, step.name)
            if step_rec and step_rec.status == StepStatus.COMPENSATED:
                continue  # Déjà compensée (reprise après crash en phase COMPENSATING)

            comp_rec = StepRecord(
                saga_id=record.id,
                step_name=step.name,
                status=StepStatus.COMPENSATING,
            )
            await loop.run_in_executor(None, self._store.upsert_step, comp_rec)

            try:
                await asyncio.wait_for(step.compensate(record.context), timeout=step.timeout)
                comp_rec.status = StepStatus.COMPENSATED
                comp_rec.completed_at = time.time()
                await loop.run_in_executor(None, self._store.upsert_step, comp_rec)
                logger.debug(f"Étape '{step.name}' compensée pour saga {record.id[:8]}…")
            except Exception as e:
                logger.error(
                    f"❌ Échec compensation étape '{step.name}' "
                    f"saga {record.id[:8]}… : {e}"
                )
                comp_rec.status = StepStatus.FAILED
                comp_rec.error = str(e)
                comp_rec.completed_at = time.time()
                await loop.run_in_executor(None, self._store.upsert_step, comp_rec)
                # On continue malgré tout pour tenter les autres compensations

        record.status = SagaStatus.COMPENSATED
        record.updated_at = time.time()
        await loop.run_in_executor(None, self._store.upsert_saga, record)
        logger.info(f"↩️  Saga {record.id[:8]}… compensée")

    # ─────────────────────────────────────────────────────────────────────────
    # Reprise après crash (recover_incomplete)
    # ─────────────────────────────────────────────────────────────────────────

    async def recover_incomplete(self) -> None:
        """
        Reprend toutes les sagas incomplètes (RUNNING ou COMPENSATING)
        trouvées dans le store au démarrage.

        Politique :
        - Heartbeat frais (< HEARTBEAT_TIMEOUT_S) → skip (instance peut-être vivante)
        - RUNNING + étape courante idempotente → reprendre depuis cette étape
        - RUNNING + étape courante non-idempotente → compenser
        - COMPENSATING → continuer la compensation
        """
        loop = asyncio.get_running_loop()
        incomplete = await loop.run_in_executor(None, self._store.get_incomplete_sagas)

        if not incomplete:
            logger.debug("recover_incomplete : aucune saga incomplète")
            return

        logger.info(f"recover_incomplete : {len(incomplete)} saga(s) à traiter")
        now = time.time()

        for record in incomplete:
            # Heartbeat frais → peut être une instance vivante, ne pas toucher
            if now - record.heartbeat_at < HEARTBEAT_TIMEOUT_S:
                logger.info(
                    f"recover_incomplete : saga {record.id[:8]}… ignorée "
                    f"(heartbeat frais il y a {now - record.heartbeat_at:.0f}s)"
                )
                continue

            definition = self._definitions.get(record.definition_name)
            if definition is None:
                logger.warning(
                    f"recover_incomplete : saga {record.id[:8]}… "
                    f"— définition '{record.definition_name}' non enregistrée, ignorée"
                )
                continue

            if record.status == SagaStatus.COMPENSATING:
                # Continuer la compensation là où elle s'est arrêtée
                logger.info(
                    f"recover_incomplete : saga {record.id[:8]}… "
                    f"en COMPENSATING → reprise de la compensation"
                )
                completed_steps = self._get_completed_steps(record, definition)
                asyncio.create_task(
                    self._compensate(record, definition, completed_steps),
                    name=f"saga.recover.compensate.{record.id[:8]}"
                )
                continue

            # Saga RUNNING — chercher l'étape courante
            if record.status == SagaStatus.RUNNING:
                current_step = self._find_current_step(record, definition)

                if current_step is None:
                    # Toutes les étapes semblent complètes → marquer COMPLETED
                    logger.info(
                        f"recover_incomplete : saga {record.id[:8]}… "
                        f"toutes étapes complètes → COMPLETED"
                    )
                    record.status = SagaStatus.COMPLETED
                    record.updated_at = time.time()
                    await loop.run_in_executor(None, self._store.upsert_saga, record)
                    continue

                if current_step.idempotent:
                    # Étape idempotente → on peut reprendre sans risque
                    logger.info(
                        f"recover_incomplete : saga {record.id[:8]}… "
                        f"étape '{current_step.name}' idempotente → reprise"
                    )
                    asyncio.create_task(
                        self._run_steps(record, definition),
                        name=f"saga.recover.run.{record.id[:8]}"
                    )
                else:
                    # Étape non-idempotente interrompue → compenser
                    logger.info(
                        f"recover_incomplete : saga {record.id[:8]}… "
                        f"étape '{current_step.name}' non-idempotente → compensation"
                    )
                    completed_steps = self._get_completed_steps(record, definition)
                    asyncio.create_task(
                        self._compensate(record, definition, completed_steps),
                        name=f"saga.recover.compensate.{record.id[:8]}"
                    )

    def _find_current_step(self,
                           record: SagaRecord,
                           definition: SagaDefinition) -> Optional[SagaStep]:
        """
        Retourne l'étape courante (première étape non COMPLETED) d'une saga,
        ou None si toutes sont terminées.
        """
        step_records = {
            sr.step_name: sr
            for sr in self._store.get_steps(record.id)
        }
        for step in definition.steps:
            sr = step_records.get(step.name)
            if sr is None or sr.status not in (StepStatus.COMPLETED, StepStatus.COMPENSATED):
                return step
        return None

    def _get_completed_steps(self,
                             record: SagaRecord,
                             definition: SagaDefinition) -> List[SagaStep]:
        """
        Retourne la liste des étapes dont le StepRecord est COMPLETED
        (dans l'ordre de définition).
        """
        step_records = {
            sr.step_name: sr
            for sr in self._store.get_steps(record.id)
        }
        return [
            step for step in definition.steps
            if step_records.get(step.name) and
               step_records[step.name].status == StepStatus.COMPLETED
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # Heartbeat
    # ─────────────────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self, saga_id: str) -> None:
        """Envoie un heartbeat toutes les HEARTBEAT_INTERVAL_S secondes."""
        loop = asyncio.get_running_loop()
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                await loop.run_in_executor(
                    None, self._store.update_heartbeat, saga_id
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat erreur pour {saga_id[:8]}… : {e}")
