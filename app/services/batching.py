"""
BatchingOrchestrator — répartiteur de requêtes LLM avec fenêtre de collecte adaptative.

Regroupe les appels LLM par modèle pour maximiser le débit tout en maintenant
une latence acceptable. Les requêtes utilisateur (priority=USER) passent en bypass
immédiat ; les requêtes BACKGROUND/BATCH/NORMAL sont accumulées dans une fenêtre
de collecte adaptative (10–100 ms) avant d'être traitées en lot.

Composants :
  - RequestPriority : Enum des niveaux de priorité
  - LLMRequest      : Requête individuelle avec Future pour le résultat
  - ModelWorker     : Worker asynchrone par modèle actif
  - BatchingOrchestrator : Orchestrateur central
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional

import aiohttp

from ..utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

OLLAMA_API_BASE: str = "http://localhost:11434"

# Fenêtre de collecte adaptative (en secondes)
WINDOW_MIN_S: float = 0.010   # 10 ms — fenêtre minimale
WINDOW_MAX_S: float = 0.100   # 100 ms — fenêtre maximale

# Taille de lot maximale par fenêtre (pour éviter les timeouts Ollama)
MAX_BATCH_SIZE: int = 16

# Timeout d'une requête individuelle (secondes)
REQUEST_TIMEOUT_S: float = 120.0

# keep_alive pendant les batchs (maintient le modèle chaud)
KEEP_ALIVE_BATCH: str = "10m"


# ─────────────────────────────────────────────────────────────────────────────
# Priorités
# ─────────────────────────────────────────────────────────────────────────────

class RequestPriority(Enum):
    """Niveaux de priorité pour les requêtes LLM."""
    BACKGROUND = auto()  # Traitement différé, pas urgent
    BATCH      = auto()  # Groupé avec d'autres, latence acceptable
    NORMAL     = auto()  # Traitement standard dans la fenêtre
    USER       = auto()  # Bypass immédiat, priorité maximale


# ─────────────────────────────────────────────────────────────────────────────
# Requête individuelle
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LLMRequest:
    """Requête LLM individuelle, avec Future pour recevoir la réponse."""
    model: str
    system_prompt: str
    user_prompt: str
    priority: RequestPriority
    future: "asyncio.Future[str]" = field(default_factory=lambda: asyncio.get_event_loop().create_future())
    created_at: float = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# Worker par modèle
# ─────────────────────────────────────────────────────────────────────────────

class ModelWorker:
    """
    Worker asynchrone dédié à un modèle Ollama.

    Collecte les requêtes BACKGROUND/BATCH/NORMAL dans une fenêtre adaptative,
    puis les traite séquentiellement (Ollama est mono-instance par modèle).
    Les requêtes USER sont injectées en tête de queue sans attendre la fenêtre.
    """

    def __init__(self,
                 model: str,
                 ollama_base: str = OLLAMA_API_BASE,
                 memory_guardian: Optional[Any] = None) -> None:
        self.model = model
        self._ollama_base = ollama_base
        self._memory_guardian = memory_guardian

        self._queue: asyncio.Queue[LLMRequest] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._running: bool = False

        # Fenêtre adaptative : ajustée selon la charge
        self._window_s: float = WINDOW_MIN_S
        self._processed_count: int = 0

    async def start(self) -> None:
        """Démarre le worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(
            self._run(), name=f"batching.worker.{self.model}"
        )
        logger.debug(f"ModelWorker démarré pour {self.model}")

    async def stop(self) -> None:
        """Arrête proprement le worker après avoir vidé la queue."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, request: LLMRequest) -> None:
        """Enfile une requête. Les requêtes USER sont marquées pour bypass."""
        await self._queue.put(request)

    async def _run(self) -> None:
        """Boucle principale : collecte une fenêtre puis traite le lot."""
        while self._running:
            batch: List[LLMRequest] = []

            # Attendre la première requête
            try:
                first = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Bypass immédiat pour USER
            if first.priority == RequestPriority.USER:
                await self._process_single(first)
                continue

            batch.append(first)

            # Collecter d'autres requêtes dans la fenêtre adaptative
            deadline = time.monotonic() + self._window_s
            while len(batch) < MAX_BATCH_SIZE:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    req = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                    if req.priority == RequestPriority.USER:
                        # Insérer la requête USER en tête — traiter le batch actuel d'abord
                        # puis traiter immédiatement la requête urgente
                        await self._process_batch(batch)
                        batch = []
                        await self._process_single(req)
                        break
                    batch.append(req)
                except asyncio.TimeoutError:
                    break
                except asyncio.CancelledError:
                    break

            if batch:
                await self._process_batch(batch)

            # Adapter la fenêtre selon la taille du lot
            self._adapt_window(len(batch) if batch else 0)

    def _adapt_window(self, batch_size: int) -> None:
        """
        Ajuste la fenêtre de collecte :
        - Si le lot est plein → réduire la fenêtre (forte charge)
        - Si le lot est petit → augmenter la fenêtre (faible charge)
        """
        if batch_size >= MAX_BATCH_SIZE * 0.8:
            self._window_s = max(self._window_s * 0.8, WINDOW_MIN_S)
        elif batch_size <= 2:
            self._window_s = min(self._window_s * 1.2, WINDOW_MAX_S)

    async def _process_single(self, request: LLMRequest) -> None:
        """Traite une requête unique (bypass USER)."""
        await self._process_batch([request])

    async def _process_batch(self, batch: List[LLMRequest]) -> None:
        """Traite un lot de requêtes séquentiellement via Ollama."""
        if not batch:
            return

        # Vérifier la disponibilité du modèle via MemoryGuardian
        if self._memory_guardian is not None:
            ok = await self._memory_guardian.request_model(
                self.model, agent="batching_orchestrator", priority=5
            )
            if not ok:
                logger.warning(
                    f"MemoryGuardian a refusé {self.model} — "
                    f"{len(batch)} requête(s) annulée(s)"
                )
                for req in batch:
                    if not req.future.done():
                        req.future.set_exception(
                            RuntimeError(f"Modèle {self.model} indisponible (budget mémoire)")
                        )
                return

        logger.debug(f"Traitement lot de {len(batch)} requête(s) pour {self.model}")

        for req in batch:
            if req.future.done():
                continue
            try:
                result = await asyncio.wait_for(
                    self._call_ollama(req),
                    timeout=REQUEST_TIMEOUT_S
                )
                req.future.set_result(result)
                self._processed_count += 1
            except asyncio.TimeoutError:
                logger.error(f"Timeout Ollama pour {self.model}")
                req.future.set_exception(TimeoutError(f"Ollama {self.model} timeout"))
            except asyncio.CancelledError:
                if not req.future.done():
                    req.future.cancel()
                raise
            except Exception as e:
                logger.error(f"Erreur Ollama {self.model}: {e}")
                if not req.future.done():
                    req.future.set_exception(e)

    async def _call_ollama(self, req: LLMRequest) -> str:
        """Appelle l'API Ollama /api/chat et retourne la réponse en texte."""
        payload = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": req.system_prompt},
                {"role": "user",   "content": req.user_prompt},
            ],
            "stream": False,
            "keep_alive": KEEP_ALIVE_BATCH,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._ollama_base}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S + 5),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Ollama status {resp.status}: {text[:200]}")
                data = await resp.json()
                return data.get("message", {}).get("content", "")


# ─────────────────────────────────────────────────────────────────────────────
# BatchingOrchestrator
# ─────────────────────────────────────────────────────────────────────────────

class BatchingOrchestrator:
    """
    Orchestrateur central de requêtes LLM avec fenêtre de collecte adaptative.

    Crée un ModelWorker par modèle à la première requête et le maintient actif.
    Gère la priorité USER (bypass immédiat) et les niveaux inférieurs (fenêtre adaptative).

    Usage :
        orchestrator = BatchingOrchestrator(memory_guardian=guardian)
        await orchestrator.start()
        response = await orchestrator.submit("mistral:7b", "Tu es utile.", "Bonjour")
        await orchestrator.stop()
    """

    def __init__(self,
                 memory_guardian: Optional[Any] = None,
                 ollama_base: str = OLLAMA_API_BASE) -> None:
        self._memory_guardian = memory_guardian
        self._ollama_base = ollama_base
        self._workers: Dict[str, ModelWorker] = {}
        self._running: bool = False
        logger.info("✅ BatchingOrchestrator initialisé")

    async def start(self) -> None:
        """Démarre l'orchestrateur (les workers démarrent à la demande)."""
        self._running = True
        logger.info("BatchingOrchestrator démarré")

    async def stop(self) -> None:
        """Arrête tous les workers actifs."""
        self._running = False
        for worker in self._workers.values():
            await worker.stop()
        self._workers.clear()
        logger.info("BatchingOrchestrator arrêté")

    async def _get_worker(self, model: str) -> ModelWorker:
        """Retourne le worker du modèle, en le créant si nécessaire."""
        if model not in self._workers:
            worker = ModelWorker(
                model=model,
                ollama_base=self._ollama_base,
                memory_guardian=self._memory_guardian,
            )
            await worker.start()
            self._workers[model] = worker
            logger.debug(f"Nouveau worker créé pour {model}")
        return self._workers[model]

    async def submit(self,
                     model: str,
                     system_prompt: str,
                     user_prompt: str,
                     priority: RequestPriority = RequestPriority.NORMAL) -> str:
        """
        Soumet une requête LLM individuelle et attend le résultat.

        Args:
            model:        Nom du modèle Ollama.
            system_prompt: Prompt système.
            user_prompt:  Prompt utilisateur.
            priority:     Priorité de la requête.

        Returns:
            Réponse textuelle du modèle.
        """
        loop = asyncio.get_running_loop()
        req = LLMRequest(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            priority=priority,
            future=loop.create_future(),
        )
        worker = await self._get_worker(model)
        await worker.enqueue(req)
        return await req.future

    async def submit_batch(self,
                           model: str,
                           requests_data: List[Dict[str, str]],
                           priority: RequestPriority = RequestPriority.BATCH) -> List[str]:
        """
        Soumet un lot de requêtes pour un même modèle.

        Args:
            model:         Nom du modèle Ollama.
            requests_data: Liste de dicts avec les clés "system" et "user".
            priority:      Priorité appliquée à toutes les requêtes du lot.

        Returns:
            Liste de réponses dans le même ordre que requests_data.
        """
        loop = asyncio.get_running_loop()
        llm_requests: List[LLMRequest] = []
        for item in requests_data:
            req = LLMRequest(
                model=model,
                system_prompt=item.get("system", ""),
                user_prompt=item.get("user", ""),
                priority=priority,
                future=loop.create_future(),
            )
            llm_requests.append(req)

        worker = await self._get_worker(model)
        for req in llm_requests:
            await worker.enqueue(req)

        results = await asyncio.gather(
            *[req.future for req in llm_requests],
            return_exceptions=True
        )

        responses: List[str] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"submit_batch erreur requête {i}: {res}")
                responses.append("")
            else:
                responses.append(str(res))
        return responses

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de chaque worker actif."""
        return {
            model: {
                "processed": worker._processed_count,
                "queue_size": worker._queue.qsize(),
                "window_ms": round(worker._window_s * 1000, 1),
            }
            for model, worker in self._workers.items()
        }
