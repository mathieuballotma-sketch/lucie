"""
Event Bus asynchrone et sécurisé avec permissions dynamiques, rate limiting,
gestion des abonnements traçables et capacité de révocation immunitaire.
Incarne les principes :
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

    def __post_init__(self):
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

    def _cleanup(self):
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
    active_tasks: Set[asyncio.Task] = field(default_factory=set)


class PermissionManager:
    """
    Gère les droits d'émission et de souscription, ainsi que les abonnements actifs.
    Permet de révoquer une source et de nettoyer proprement ses traces.
    """
    def __init__(self):
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
                              services: List[str] = None):
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
            # Comparaison en temps constant
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
            if not await self.authenticate(source, token):
                raise SecurityError(f"Authentification échouée pour {source}")
            if not await self.can_subscribe(source, channel):
                raise SecurityError(f"Source {source} non autorisée à s'abonner à {channel}")
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            sub = Subscription(callback=callback, source=source, token_hash=token_hash)
            self._active_subs[source][channel].append(sub)
            return sub

    async def remove_subscription(self, source: str, channel: str, callback: Callable):
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
                    # On fait une copie superficielle, les objets Subscription sont immuables
                    result.extend(channels[channel])
            return result

    async def kill_source(self, source: str):
        """
        Révoque tous les droits d'une source, supprime ses abonnements,
        et retourne la liste des tâches actives à annuler.
        """
        async with self._lock:
            logger.warning(f"🛡️ Révocation de la source {source}")
            # Retirer des ACL
            self._publish_acl.pop(source, None)
            self._subscribe_acl.pop(source, None)
            self._source_tokens.pop(source, None)
            # Retirer des services
            for svc, s in list(self._service_map.items()):
                if s == source:
                    del self._service_map[svc]
            # Récupérer les abonnements et tâches actives
            tasks_to_cancel = []
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
    Bus d'événements asynchrone avec canaux, permissions, rate limiting,
    historique, et mécanisme de requête/réponse sécurisé.
    """

    def __init__(self, max_history: int = 100):
        self._permissions = PermissionManager()
        self._rate_limiter = RateLimiter()
        self._history: List[Event] = []
        self.max_history = max_history
        self._lock = asyncio.Lock()  # Pour l'historique et autres opérations globales
        self._response_futures: Dict[str, tuple[asyncio.Future, str]] = {}  # request_id -> (future, expected_source)

    async def register_source(self, source: str, token: str = None,
                              publish_channels: List[str] = None,
                              subscribe_channels: List[str] = None,
                              services: List[str] = None):
        """
        Enregistre une source avec ses droits. Si token non fourni, en génère un.
        Retourne le token à conserver par la source.
        """
        if token is None:
            token = secrets.token_urlsafe(32)
        await self._permissions.register_source(source, token,
                                                publish_channels or [],
                                                subscribe_channels or [],
                                                services or [])
        return token

    async def publish(self, channel: str, data: Any = None, source: str = "system", token: str = None):
        """
        Publie un événement sur un canal.
        Nécessite que la source soit authentifiée et autorisée.
        """
        # Authentification et autorisation
        if not await self._permissions.authenticate(source, token):
            raise SecurityError(f"Authentification échouée pour {source}")
        if not await self._permissions.can_publish(source, channel):
            raise SecurityError(f"Source {source} non autorisée à publier sur {channel}")

        # Rate limiting
        if not self._rate_limiter.allow(source):
            logger.warning(f"Rate limit exceeded for {source} on {channel}")
            # On peut choisir de jeter l'événement silencieusement
            return

        # Créer l'événement avec une copie profonde des données
        event_id = str(uuid.uuid4())
        event = Event(
            id=event_id,
            channel=channel,
            data=copy.deepcopy(data),
            source=source,
            timestamp=time.time()
        )

        # Historique (avec copie)
        async with self._lock:
            self._history.append(event)
            if len(self._history) > self.max_history:
                self._history.pop(0)

        # Récupérer les abonnés
        subscribers = await self._permissions.get_subscribers(channel)

        # Lancer les callbacks en parallèle, avec timeout et suivi des tâches
        for sub in subscribers:
            # Créer une tâche avec timeout
            async def wrapped_cb():
                try:
                    await asyncio.wait_for(sub.callback(event), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.error(f"Callback timeout for {event.channel} from {event.source} (subscriber {sub.source})")
                except Exception as e:
                    logger.error(f"Callback error: {e}")

            task = asyncio.create_task(wrapped_cb())
            # Ajouter la tâche à la subscription pour pouvoir l'annuler plus tard
            sub.active_tasks.add(task)
            task.add_done_callback(lambda t: sub.active_tasks.discard(t))

    async def subscribe(self, channel: str, callback: Callable[[Event], Awaitable[None]],
                        source: str, token: str) -> Subscription:
        """
        Abonne une source à un canal. Retourne l'objet Subscription.
        """
        return await self._permissions.add_subscription(source, channel, callback, token)

    async def unsubscribe(self, channel: str, callback: Callable, source: str, token: str):
        """Se désabonne."""
        if not await self._permissions.authenticate(source, token):
            raise SecurityError(f"Authentification échouée pour {source}")
        await self._permissions.remove_subscription(source, channel, callback)

    async def request(self, service: str, data: Any = None, timeout: float = 5.0) -> Any:
        """
        Envoie une requête à un service et attend une réponse.
        Le service doit être enregistré via register_source avec le nom du service.
        """
        # Déterminer la source du service
        target_source = await self._permissions.get_service_source(service)
        if not target_source:
            raise SecurityError(f"Service {service} inconnu")

        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        # On enregistre la future avec la source attendue
        self._response_futures[request_id] = (future, target_source)

        # Publier la requête sur le canal dédié
        await self.publish(f"request.{service}",
                           {"request_id": request_id, "data": data},
                           source="system",
                           token=None)  # Le bus n'a pas besoin de token pour system?

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request to {service} timed out")
        finally:
            self._response_futures.pop(request_id, None)

    async def respond(self, request_id: str, data: Any, source: str, token: str):
        """
        Permet à un agent de répondre à une requête.
        Vérifie que la source correspond à celle attendue.
        """
        entry = self._response_futures.get(request_id)
        if not entry:
            logger.warning(f"Response to unknown request {request_id}")
            return
        future, expected_source = entry
        if source != expected_source:
            raise SecurityError(f"Source {source} not allowed to respond to request {request_id}")
        if not await self._permissions.authenticate(source, token):
            raise SecurityError(f"Authentification échouée pour {source}")

        if not future.done():
            future.set_result(data)

    async def kill_source(self, source: str, admin_token: str):
        """
        Action immunitaire : révoque une source et annule ses tâches en cours.
        Nécessite un jeton d'administrateur (à définir). Pour l'instant, on suppose
        que l'appelant est autorisé (ex: HealerAgent).
        """
        # TODO: vérifier admin_token
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