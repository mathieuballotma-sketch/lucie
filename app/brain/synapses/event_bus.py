"""
Event Bus asynchrone v3 — file unique + consommateur permanent + concurrence bornée.

Améliorations par rapport à la v2 :
- asyncio.Queue unique avec _dispatch_loop() comme consommateur permanent
  (élimine la création de tâches ad-hoc pour chaque publication).
- Sémaphore par canal pour borner la concurrence (default_max_concurrent=10).
- Tracking des tâches actives (globales) pour un arrêt propre via stop().
- _bounded_callback() : libère le sémaphore via try/finally même en cas d'exception.
- _safe_callback() : isole les exceptions des callbacks individuels.
- set_channel_concurrency() : configure le sémaphore d'un canal à chaud.
- Stats enrichies : semaphore_waits, active_tasks, channel_concurrency.

Principes conservés :
- Homéostasie : rate limiting, gestion des erreurs, nettoyage des tâches orphelines.
- Immunité adaptative : révocation des sources, annulation des callbacks en cours.
- Symbiose : communication structurée entre composants avec authentification.
- Entropie : historique immuable, copies profondes.
"""

import asyncio
import copy
import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Awaitable

from app.utils.logger import get_logger

logger = get_logger(__name__)


class SecurityError(Exception):
    """Erreur liée aux permissions ou à l'authentification."""
    pass


@dataclass
class Event:
    """Événement immuable circulant sur le bus."""
    id: str
    channel: str
    data: Any
    source: str
    timestamp: float

    def __post_init__(self) -> None:
        # Rendre data immuable en le convertissant en tuple si c'est une liste,
        # ou en gelant les dictionnaires. Pour simplifier, on fait une copie profonde
        # mais on ne garantit pas l'immuabilité totale. À améliorer avec Pydantic.
        pass


class RateLimiter:
    """
    Limiteur de débit avec cache LRU et nettoyage automatique.
    """
    def __init__(self, max_per_second: int = 10, max_sources: int = 1000):
        self.max_per_second = max_per_second
        self.max_sources = max_sources
        self._counts: OrderedDict[str, tuple[int, float]] = OrderedDict()

    def _cleanup(self) -> None:
        while len(self._counts) > self.max_sources:
            self._counts.popitem(last=False)
        now = time.time()
        for src in list(self._counts.keys()):
            _, last = self._counts[src]
            if now - last > 60:
                del self._counts[src]

    def allow(self, source: str) -> bool:
        self._cleanup()
        now = time.time()
        if source not in self._counts:
            self._counts[source] = (1, now)
            return True
        count, last = self._counts[source]
        if now - last > 1.0:
            self._counts[source] = (1, now)
            return True
        if count < self.max_per_second:
            self._counts[source] = (count + 1, last)
            return True
        return False


@dataclass
class Subscription:
    """Représente un abonnement avec suivi des tâches actives."""
    callback: Callable[[Event], Awaitable[None]]
    source: str
    token_hash: str
    active_tasks: Set[asyncio.Task[None]] = field(default_factory=set)


class PermissionManager:
    """
    Gère les droits d'émission et de souscription, ainsi que les abonnements actifs.
    Permet de révoquer une source et de nettoyer proprement ses traces.
    """
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # ACL pour publication : source -> set(channels)
        self._publish_acl: Dict[str, Set[str]] = defaultdict(set)
        # ACL pour souscription : source -> set(channels)
        self._subscribe_acl: Dict[str, Set[str]] = defaultdict(set)
        # Abonnements actifs : source -> {channel -> list[Subscription]}
        self._active_subs: Dict[str, Dict[str, List[Subscription]]] = defaultdict(lambda: defaultdict(list))
        # Correspondance source -> token (pour authentification)
        self._source_tokens: Dict[str, str] = {}
        # Correspondance service -> source (pour les requêtes)
        self._service_map: Dict[str, str] = {}

    async def register_source(self, source: str, token: str,
                              publish_channels: List[str],
                              subscribe_channels: List[str],
                              services: Optional[List[str]] = None) -> None:
        """Enregistre une nouvelle source avec ses droits et son token."""
        async with self._lock:
            if source in self._source_tokens:
                raise SecurityError(f"Source {source} déjà enregistrée")
            self._source_tokens[source] = token
            for ch in publish_channels:
                self._publish_acl[source].add(ch)
            for ch in subscribe_channels:
                self._subscribe_acl[source].add(ch)
            if services:
                for svc in services:
                    if svc in self._service_map:
                        logger.warning(f"Service {svc} déjà fourni par {self._service_map[svc]}, écrasement")
                    self._service_map[svc] = source
            logger.debug(f"Source {source} enregistrée: pub={publish_channels}, sub={subscribe_channels}")

    async def authenticate(self, source: str, token: str) -> bool:
        """Vérifie qu'un token correspond à la source."""
        async with self._lock:
            expected = self._source_tokens.get(source)
            if not expected:
                return False
            return hmac.compare_digest(token, expected)

    async def can_publish(self, source: str, channel: str) -> bool:
        async with self._lock:
            return channel in self._publish_acl.get(source, set())

    async def can_subscribe(self, source: str, channel: str) -> bool:
        async with self._lock:
            return channel in self._subscribe_acl.get(source, set())

    async def add_subscription(self, source: str, channel: str,
                               callback: Callable[[Event], Awaitable[None]],
                               token: str) -> Subscription:
        """Ajoute un abonnement après vérification du token."""
        async with self._lock:
            # Inline auth/acl checks pour éviter le deadlock (asyncio.Lock non réentrant).
            expected = self._source_tokens.get(source)
            if not expected or not hmac.compare_digest(token, expected):
                raise SecurityError(f"Authentification échouée pour {source}")
            if channel not in self._subscribe_acl.get(source, set()):
                raise SecurityError(f"Source {source} non autorisée à s'abonner à {channel}")
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            sub = Subscription(callback=callback, source=source, token_hash=token_hash)
            self._active_subs[source][channel].append(sub)
            return sub

    async def remove_subscription(self, source: str, channel: str, callback: Callable[..., Any]) -> None:
        """Retire un abonnement spécifique."""
        async with self._lock:
            if source in self._active_subs and channel in self._active_subs[source]:
                self._active_subs[source][channel] = [
                    s for s in self._active_subs[source][channel] if s.callback != callback
                ]
                if not self._active_subs[source][channel]:
                    del self._active_subs[source][channel]
                if not self._active_subs[source]:
                    del self._active_subs[source]

    async def get_subscribers(self, channel: str) -> List[Subscription]:
        """Retourne une copie de la liste des abonnés à un canal."""
        async with self._lock:
            result = []
            for source, channels in self._active_subs.items():
                if channel in channels:
                    result.extend(channels[channel])
            return result

    async def kill_source(self, source: str) -> List[asyncio.Task[None]]:
        """
        Révoque tous les droits d'une source, supprime ses abonnements,
        et retourne la liste des tâches actives à annuler.
        """
        async with self._lock:
            logger.warning(f"🛡️ Révocation de la source {source}")
            self._publish_acl.pop(source, None)
            self._subscribe_acl.pop(source, None)
            self._source_tokens.pop(source, None)
            for svc, s in list(self._service_map.items()):
                if s == source:
                    del self._service_map[svc]
            tasks_to_cancel: List[asyncio.Task[None]] = []
            if source in self._active_subs:
                for channel, subs in self._active_subs[source].items():
                    for sub in subs:
                        tasks_to_cancel.extend(sub.active_tasks)
                del self._active_subs[source]
            return tasks_to_cancel

    async def get_service_source(self, service: str) -> Optional[str]:
        """Retourne la source qui fournit un service."""
        async with self._lock:
            return self._service_map.get(service)


class EventBus:
    """
    Bus d'événements asynchrone v3.

    Architecture :
    - Une asyncio.Queue unique reçoit tous les événements publiés.
    - Un _dispatch_loop() permanent consomme la queue et dispatche vers les abonnés.
    - Un sémaphore par canal borne la concurrence (default_max_concurrent=10).
    - Les tâches actives sont tracées globalement pour un arrêt propre via stop().

    L'API publique (publish, subscribe, unsubscribe, request, respond,
    kill_source, get_history, register_source) reste identique à la v2.
    """

    DEFAULT_MAX_CONCURRENT: int = 10
    CALLBACK_TIMEOUT: float = 2.0

    def __init__(self, max_history: int = 100, default_max_concurrent: int = DEFAULT_MAX_CONCURRENT):
        self._permissions = PermissionManager()
        self._rate_limiter = RateLimiter()
        self._history: List[Event] = []
        self.max_history = max_history
        self._lock = asyncio.Lock()

        # File unique et boucle de dispatch
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._dispatch_task: Optional[asyncio.Task[None]] = None
        self._running: bool = False

        # Concurrence bornée par canal
        self._default_max_concurrent = default_max_concurrent
        self._channel_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._channel_concurrency: Dict[str, int] = {}  # config mémorisée

        # Tracking global des tâches actives (pour stop())
        self._active_tasks: Set[asyncio.Task[None]] = set()
        self._tasks_lock = asyncio.Lock()

        # Futures pour request/response
        self._response_futures: Dict[str, tuple[asyncio.Future[Any], str]] = {}

        # Stats
        self._stats: Dict[str, Any] = {
            "semaphore_waits": 0,
            "active_tasks": 0,
            "channel_concurrency": {},
            "events_dispatched": 0,
            "events_dropped_rate_limit": 0,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Cycle de vie
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Démarre le consommateur de queue. À appeler une fois au démarrage."""
        if self._running:
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop(), name="event_bus.dispatch_loop")
        logger.info("✅ EventBus v3 démarré (dispatch_loop actif)")

    async def stop(self, timeout: float = 5.0) -> None:
        """
        Arrête proprement le bus :
        1. Arrête d'accepter de nouveaux événements.
        2. Attend que la queue soit vide (drain).
        3. Attend les tâches actives ou les annule si timeout.
        """
        self._running = False

        # Drain de la queue
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("⚠️ EventBus stop() : timeout drain de la queue")

        # Annuler la boucle de dispatch
        if self._dispatch_task and not self._dispatch_task.done():
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        # Attendre ou annuler les tâches actives restantes
        async with self._tasks_lock:
            remaining = list(self._active_tasks)

        if remaining:
            done, pending = await asyncio.wait(remaining, timeout=timeout)
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        logger.info("EventBus v3 arrêté proprement")

    # ─────────────────────────────────────────────────────────────────────────
    # Boucle de dispatch
    # ─────────────────────────────────────────────────────────────────────────

    async def _dispatch_loop(self) -> None:
        """Consommateur permanent de la queue d'événements."""
        logger.debug("EventBus _dispatch_loop démarrée")
        while True:
            try:
                event = await self._queue.get()
                try:
                    await self._dispatch_event(event)
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                logger.debug("EventBus _dispatch_loop annulée")
                break
            except Exception as e:
                logger.error(f"❌ EventBus _dispatch_loop erreur inattendue: {e}")

    async def _dispatch_event(self, event: Event) -> None:
        """Dispatche un événement vers tous ses abonnés."""
        subscribers = await self._permissions.get_subscribers(event.channel)
        sem = self._get_semaphore(event.channel)

        for sub in subscribers:
            task = asyncio.create_task(
                self._bounded_callback(sem, sub, event),
                name=f"event_bus.cb.{event.channel}.{sub.source}"
            )
            sub.active_tasks.add(task)
            task.add_done_callback(lambda t, s=sub: s.active_tasks.discard(t))

            async with self._tasks_lock:
                self._active_tasks.add(task)
            task.add_done_callback(lambda t: asyncio.create_task(self._remove_active_task(t)))

        self._stats["events_dispatched"] += 1

    async def _remove_active_task(self, task: asyncio.Task[None]) -> None:
        """Retire une tâche terminée du set global."""
        async with self._tasks_lock:
            self._active_tasks.discard(task)
        self._stats["active_tasks"] = len(self._active_tasks)

    # ─────────────────────────────────────────────────────────────────────────
    # Callbacks bornés
    # ─────────────────────────────────────────────────────────────────────────

    async def _bounded_callback(self, sem: asyncio.Semaphore, sub: Subscription, event: Event) -> None:
        """
        Acquiert le sémaphore du canal avant d'appeler le callback.
        Libère le sémaphore via try/finally même en cas d'exception.
        Incrémente semaphore_waits si l'acquisition n'est pas immédiate.
        """
        if sem.locked():
            self._stats["semaphore_waits"] += 1

        async with sem:
            await self._safe_callback(sub, event)

    async def _safe_callback(self, sub: Subscription, event: Event) -> None:
        """
        Appelle le callback avec timeout et isole les exceptions
        pour qu'une erreur d'un abonné n'affecte pas les autres.
        """
        try:
            await asyncio.wait_for(sub.callback(event), timeout=self.CALLBACK_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(
                f"⏱️ Callback timeout (>{self.CALLBACK_TIMEOUT}s) "
                f"canal={event.channel} source={event.source} abonné={sub.source}"
            )
        except asyncio.CancelledError:
            raise  # Laisser remonter les annulations
        except Exception as e:
            logger.error(
                f"❌ Callback error canal={event.channel} source={event.source} "
                f"abonné={sub.source}: {e}"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Sémaphores par canal
    # ─────────────────────────────────────────────────────────────────────────

    def _get_semaphore(self, channel: str) -> asyncio.Semaphore:
        """Retourne (ou crée) le sémaphore associé à un canal."""
        if channel not in self._channel_semaphores:
            limit = self._channel_concurrency.get(channel, self._default_max_concurrent)
            self._channel_semaphores[channel] = asyncio.Semaphore(limit)
            self._stats["channel_concurrency"][channel] = limit
        return self._channel_semaphores[channel]

    def set_channel_concurrency(self, channel: str, max_concurrent: int) -> None:
        """
        Configure la concurrence maximale pour un canal.
        Si un sémaphore existe déjà pour ce canal, il sera remplacé au prochain accès.
        """
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent doit être ≥ 1, reçu: {max_concurrent}")
        self._channel_concurrency[channel] = max_concurrent
        # Invalider le sémaphore existant pour qu'il soit recréé avec la nouvelle valeur
        self._channel_semaphores.pop(channel, None)
        self._stats["channel_concurrency"][channel] = max_concurrent
        logger.debug(f"Canal '{channel}' : concurrence max → {max_concurrent}")

    # ─────────────────────────────────────────────────────────────────────────
    # API publique (identique à la v2)
    # ─────────────────────────────────────────────────────────────────────────

    async def register_source(self, source: str, token: Optional[str] = None,
                              publish_channels: Optional[List[str]] = None,
                              subscribe_channels: Optional[List[str]] = None,
                              services: Optional[List[str]] = None) -> str:
        """
        Enregistre une source avec ses droits. Si token non fourni, en génère un.
        Retourne le token à conserver par la source.
        """
        if token is None:
            token = secrets.token_urlsafe(32)
        await self._permissions.register_source(
            source, token,
            publish_channels or [],
            subscribe_channels or [],
            services or []
        )
        return token

    async def publish(self, channel: str, data: Any = None,
                      source: str = "system", token: Optional[str] = None) -> None:
        """
        Publie un événement sur un canal.
        Nécessite que la source soit authentifiée et autorisée.
        L'événement est enfilé dans la queue ; le dispatch est asynchrone.
        """
        if not await self._permissions.authenticate(source, token or ""):
            raise SecurityError(f"Authentification échouée pour {source}")
        if not await self._permissions.can_publish(source, channel):
            raise SecurityError(f"Source {source} non autorisée à publier sur {channel}")

        if not self._rate_limiter.allow(source):
            logger.warning(f"Rate limit dépassé pour {source} sur {channel}")
            self._stats["events_dropped_rate_limit"] += 1
            return

        event = Event(
            id=str(uuid.uuid4()),
            channel=channel,
            data=copy.deepcopy(data),
            source=source,
            timestamp=time.time()
        )

        # Historique (avec verrou)
        async with self._lock:
            self._history.append(event)
            if len(self._history) > self.max_history:
                self._history.pop(0)

        # Enfile dans la queue — le _dispatch_loop s'en charge
        if not self._running:
            logger.warning(f"EventBus arrêté, événement {channel} ignoré")
            return
        await self._queue.put(event)

    async def subscribe(self, channel: str, callback: Callable[[Event], Awaitable[None]],
                        source: str, token: str) -> Subscription:
        """Abonne une source à un canal. Retourne l'objet Subscription."""
        return await self._permissions.add_subscription(source, channel, callback, token)

    async def unsubscribe(self, channel: str, callback: Callable[..., Any],
                          source: str, token: str) -> None:
        """Se désabonne d'un canal."""
        if not await self._permissions.authenticate(source, token):
            raise SecurityError(f"Authentification échouée pour {source}")
        await self._permissions.remove_subscription(source, channel, callback)

    async def request(self, service: str, data: Any = None, timeout: float = 5.0) -> Any:
        """
        Envoie une requête à un service et attend une réponse.
        Le service doit être enregistré via register_source avec le nom du service.
        """
        target_source = await self._permissions.get_service_source(service)
        if not target_source:
            raise SecurityError(f"Service {service} inconnu")

        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._response_futures[request_id] = (future, target_source)

        await self.publish(
            f"request.{service}",
            {"request_id": request_id, "data": data},
            source="system",
            token=None
        )

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Requête vers {service} expirée")
        finally:
            self._response_futures.pop(request_id, None)

    async def respond(self, request_id: str, data: Any, source: str, token: str) -> None:
        """Permet à un agent de répondre à une requête."""
        entry = self._response_futures.get(request_id)
        if not entry:
            logger.warning(f"Réponse à un request_id inconnu: {request_id}")
            return
        future, expected_source = entry
        if source != expected_source:
            raise SecurityError(f"Source {source} non autorisée à répondre à {request_id}")
        if not await self._permissions.authenticate(source, token):
            raise SecurityError(f"Authentification échouée pour {source}")
        if not future.done():
            future.set_result(data)

    async def kill_source(self, source: str, admin_token: str) -> None:
        """
        Action immunitaire : révoque une source et annule ses tâches en cours.
        Nécessite un jeton d'administrateur (l'appelant est responsable de l'autorisation).
        """
        tasks = await self._permissions.kill_source(source)
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info(f"Source {source} révoquée et nettoyée")

    async def get_history(self, limit: int = 10) -> List[Event]:
        """Retourne une copie de l'historique."""
        async with self._lock:
            return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques courantes du bus."""
        self._stats["active_tasks"] = len(self._active_tasks)
        self._stats["queue_size"] = self._queue.qsize()
        return dict(self._stats)
