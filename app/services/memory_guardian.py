"""
MemoryGuardianAgent — surveillance de la pression mémoire et gestion des modèles Ollama.

Surveille en continu la pression mémoire du système (via vm_stat sur macOS) et
gère un budget de modèles Ollama de 10 Go sur MacBook Air M3 16 Go.

Composants :
  - MemoryPressure : Enum des niveaux de pression (GREEN/YELLOW/RED/CRITICAL)
  - ModelRecord    : Suivi d'un modèle chargé (taille, usages, dernière utilisation)
  - MemoryGuardian : Agent principal — monitoring, éviction LRU pondérée, API publique
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import aiohttp

from ..utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

# Tailles approximatives des modèles en Go (empreinte VRAM / RAM unifiée)
MODEL_SIZES: Dict[str, float] = {
    "mistral:7b":          4.1,
    "mistral:7b-instruct": 4.1,
    "llama3.2:3b":         2.0,
    "llama3.2:1b":         1.3,
    "phi3:mini":           2.3,
    "phi3:medium":         7.9,
    "nomic-embed-text":    0.6,
}

# Modèle préféré par agent (pour le préchargement prédictif)
AGENT_MODEL_MAP: Dict[str, str] = {
    "planner":        "mistral:7b-instruct",
    "coder":          "mistral:7b-instruct",
    "reviewer":       "llama3.2:3b",
    "summarizer":     "llama3.2:3b",
    "classifier":     "phi3:mini",
    "embedder":       "nomic-embed-text",
    "multi_modal":    "phi3:medium",
}

# Budget mémoire modèles sur MacBook Air M3 16 Go (en Go)
MODEL_MEMORY_BUDGET_GB: float = 10.0
OLLAMA_API_BASE: str = "http://localhost:11434"

# Seuils vm_stat pour la pression mémoire (pages libres / pages totales)
PRESSURE_YELLOW: float = 0.20   # < 20 % libre → YELLOW
PRESSURE_RED: float = 0.10      # < 10 % libre → RED
PRESSURE_CRITICAL: float = 0.05  # < 5 % libre → CRITICAL
PAGE_SIZE_BYTES: int = 16_384   # Taille d'une page mémoire sur Apple Silicon (16 Ko)

MONITORING_INTERVAL_S: float = 2.0  # Fréquence de sondage vm_stat


# ─────────────────────────────────────────────────────────────────────────────
# Enum — niveaux de pression
# ─────────────────────────────────────────────────────────────────────────────

class MemoryPressure(Enum):
    """Niveau de pression mémoire système."""
    GREEN    = "green"     # Situation normale
    YELLOW   = "yellow"    # Attention — commencer à libérer
    RED      = "red"       # Urgent — éviction nécessaire
    CRITICAL = "critical"  # Critique — action immédiate


# ─────────────────────────────────────────────────────────────────────────────
# Suivi des modèles chargés
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelRecord:
    """Enregistrement d'un modèle actuellement chargé en mémoire."""
    name: str
    size_gb: float
    load_time: float = field(default_factory=time.time)
    last_use: float  = field(default_factory=time.time)
    use_count: int   = 0

    def utility(self) -> float:
        """
        Score d'utilité LRU pondéré pour la politique d'éviction.

        utility = use_count / (time_since_use * size_gb)

        Un modèle rarement utilisé, utilisé il y a longtemps, et volumineux
        aura un score faible → évincé en priorité.
        """
        time_since_use = max(time.time() - self.last_use, 0.001)
        return self.use_count / (time_since_use * max(self.size_gb, 0.1))


# ─────────────────────────────────────────────────────────────────────────────
# MemoryGuardian — agent principal
# ─────────────────────────────────────────────────────────────────────────────

class MemoryGuardian:
    """
    Agent système qui surveille la pression mémoire macOS et gère le budget
    des modèles Ollama chargés en mémoire unifiée.

    Fonctionnement :
    - Boucle de monitoring toutes les 2 s via vm_stat.
    - Politique d'éviction LRU pondérée quand le budget est dépassé.
    - API request_model() / preload_model() pour les agents consommateurs.
    - Publie sur l'EventBus : memory.pressure_changed, memory.model_loaded,
      memory.model_unloaded.
    """

    def __init__(self,
                 event_bus: Optional[Any] = None,
                 token: Optional[str] = None,
                 budget_gb: float = MODEL_MEMORY_BUDGET_GB,
                 ollama_base: str = OLLAMA_API_BASE) -> None:
        self._event_bus = event_bus
        self._token = token
        self._budget_gb = budget_gb
        self._ollama_base = ollama_base

        # Modèles actuellement suivis (pas forcément chargés dans Ollama)
        self._loaded_models: Dict[str, ModelRecord] = {}
        self._lock = asyncio.Lock()

        # État courant de la pression
        self._pressure: MemoryPressure = MemoryPressure.GREEN
        self._running: bool = False
        self._monitor_task: Optional[asyncio.Task[None]] = None

        logger.info(
            f"✅ MemoryGuardian initialisé — budget: {budget_gb:.1f} Go, "
            f"Ollama: {ollama_base}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Cycle de vie
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Démarre la boucle de monitoring en arrière-plan."""
        if self._running:
            return
        self._running = True
        await self._sync_with_ollama()
        self._monitor_task = asyncio.create_task(
            self._monitoring_loop(), name="memory_guardian.monitor"
        )
        logger.info("MemoryGuardian démarré")

    async def stop(self) -> None:
        """Arrête proprement la boucle de monitoring."""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("MemoryGuardian arrêté")

    # ─────────────────────────────────────────────────────────────────────────
    # Monitoring
    # ─────────────────────────────────────────────────────────────────────────

    async def _monitoring_loop(self) -> None:
        """Boucle principale : sonde vm_stat toutes les MONITORING_INTERVAL_S secondes."""
        while self._running:
            try:
                new_pressure = await self._read_memory_pressure()
                if new_pressure != self._pressure:
                    old = self._pressure
                    self._pressure = new_pressure
                    logger.info(f"Pression mémoire : {old.value} → {new_pressure.value}")
                    await self._on_pressure_changed(old, new_pressure)

                if self._pressure in (MemoryPressure.RED, MemoryPressure.CRITICAL):
                    await self._evict_if_needed()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ MemoryGuardian monitoring erreur: {e}")

            await asyncio.sleep(MONITORING_INTERVAL_S)

    async def _read_memory_pressure(self) -> MemoryPressure:
        """
        Lit la pression mémoire via vm_stat (macOS).
        Retourne le niveau de pression correspondant.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "vm_stat",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            return self._parse_vm_stat(stdout.decode())
        except asyncio.TimeoutError:
            logger.warning("vm_stat timeout — pression inconnue, on retourne GREEN")
            return MemoryPressure.GREEN
        except Exception as e:
            logger.warning(f"vm_stat erreur: {e}")
            return MemoryPressure.GREEN

    @staticmethod
    def _parse_vm_stat(output: str) -> MemoryPressure:
        """Parse la sortie de vm_stat et retourne le niveau de pression."""
        pages: Dict[str, int] = {}
        for line in output.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().rstrip(".")
            try:
                pages[key] = int(value)
            except ValueError:
                pass

        free   = pages.get("Pages free", 0)
        wired  = pages.get("Pages wired down", 0)
        active = pages.get("Pages active", 0)
        inactive = pages.get("Pages inactive", 0)
        total = free + wired + active + inactive

        if total == 0:
            return MemoryPressure.GREEN

        free_ratio = free / total
        if free_ratio < PRESSURE_CRITICAL:
            return MemoryPressure.CRITICAL
        if free_ratio < PRESSURE_RED:
            return MemoryPressure.RED
        if free_ratio < PRESSURE_YELLOW:
            return MemoryPressure.YELLOW
        return MemoryPressure.GREEN

    async def _on_pressure_changed(self,
                                   old: MemoryPressure,
                                   new: MemoryPressure) -> None:
        """Publie l'événement de changement de pression sur l'EventBus."""
        await self._publish("memory.pressure_changed", {
            "old": old.value,
            "new": new.value,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Éviction LRU pondérée
    # ─────────────────────────────────────────────────────────────────────────

    def _used_budget_gb(self) -> float:
        """Retourne le budget utilisé en Go."""
        return sum(r.size_gb for r in self._loaded_models.values())

    async def _evict_if_needed(self) -> None:
        """
        Évince les modèles les moins utiles jusqu'à ce que le budget soit respecté
        ou que la pression revienne à un niveau acceptable.
        """
        async with self._lock:
            while self._used_budget_gb() > self._budget_gb and self._loaded_models:
                # Modèle avec le score d'utilité le plus bas → évincé en premier
                victim = min(self._loaded_models.values(), key=lambda r: r.utility())
                logger.info(
                    f"⬇️ Éviction LRU : {victim.name} "
                    f"(utilité={victim.utility():.4f}, {victim.size_gb:.1f} Go)"
                )
                await self._unload_model(victim.name)

    async def _unload_model(self, model_name: str) -> None:
        """
        Demande à Ollama de libérer un modèle (keep_alive=0).
        Supprime le ModelRecord local. Doit être appelé sous self._lock.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._ollama_base}/api/generate",
                    json={"model": model_name, "keep_alive": 0},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Ollama /api/generate keep_alive=0 status {resp.status}")
        except Exception as e:
            logger.warning(f"Impossible de décharger {model_name} via Ollama: {e}")

        self._loaded_models.pop(model_name, None)
        await self._publish("memory.model_unloaded", {"model": model_name})
        logger.debug(f"Modèle {model_name} supprimé du registre local")

    # ─────────────────────────────────────────────────────────────────────────
    # Synchronisation avec Ollama
    # ─────────────────────────────────────────────────────────────────────────

    async def _sync_with_ollama(self) -> None:
        """
        Synchronise le registre local avec les modèles actuellement chargés
        dans Ollama (GET /api/ps).
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._ollama_base}/api/ps",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Ollama /api/ps status {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            logger.warning(f"Ollama /api/ps inaccessible: {e}")
            return

        async with self._lock:
            for model_info in data.get("models", []):
                name = model_info.get("name", "")
                size_bytes = model_info.get("size", 0)
                size_gb = size_bytes / (1024 ** 3) if size_bytes else MODEL_SIZES.get(name, 2.0)
                if name not in self._loaded_models:
                    self._loaded_models[name] = ModelRecord(name=name, size_gb=size_gb)
                    logger.debug(f"Sync Ollama : modèle détecté {name} ({size_gb:.2f} Go)")

        logger.info(
            f"Sync Ollama : {len(self._loaded_models)} modèle(s) en mémoire, "
            f"budget utilisé : {self._used_budget_gb():.2f} / {self._budget_gb:.1f} Go"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # API publique
    # ─────────────────────────────────────────────────────────────────────────

    async def request_model(self,
                            model: str,
                            agent: str = "unknown",
                            priority: int = 5) -> bool:
        """
        Demande l'utilisation d'un modèle par un agent.

        Retourne True si le modèle est (ou peut être) disponible, False si le budget
        est épuisé et qu'aucune éviction n'a libéré suffisamment d'espace.

        Args:
            model:    Nom du modèle Ollama (ex: "mistral:7b-instruct").
            agent:    Nom de l'agent demandeur (pour les logs et la traçabilité).
            priority: Priorité de la demande (1=faible, 10=haute).
        """
        size_gb = MODEL_SIZES.get(model, 2.0)

        async with self._lock:
            if model in self._loaded_models:
                rec = self._loaded_models[model]
                rec.last_use = time.time()
                rec.use_count += 1
                logger.debug(f"request_model({model}) par {agent} : déjà chargé")
                return True

        # Le modèle n'est pas encore chargé — vérifie le budget
        async with self._lock:
            available = self._budget_gb - self._used_budget_gb()
            if available >= size_gb:
                self._loaded_models[model] = ModelRecord(name=model, size_gb=size_gb)
                logger.info(f"✅ request_model({model}) par {agent} : accepté ({size_gb:.1f} Go)")
                await self._publish("memory.model_loaded", {"model": model, "agent": agent})
                return True

        # Budget insuffisant — tenter une éviction
        logger.info(
            f"request_model({model}) par {agent} : budget insuffisant "
            f"({self._used_budget_gb():.2f}/{self._budget_gb:.1f} Go) — éviction"
        )
        await self._evict_if_needed()

        async with self._lock:
            available = self._budget_gb - self._used_budget_gb()
            if available >= size_gb:
                self._loaded_models[model] = ModelRecord(name=model, size_gb=size_gb)
                logger.info(f"✅ request_model({model}) par {agent} : accepté après éviction")
                await self._publish("memory.model_loaded", {"model": model, "agent": agent})
                return True

        logger.warning(
            f"⚠️ request_model({model}) par {agent} : budget épuisé après éviction, refus"
        )
        return False

    async def preload_model(self, model: str) -> bool:
        """
        Précharge un modèle en envoyant un prompt vide à Ollama (keep_alive standard).
        Retourne True si le préchargement a démarré, False si refusé par le budget.
        """
        accepted = await self.request_model(model, agent="preloader", priority=1)
        if not accepted:
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._ollama_base}/api/generate",
                    json={"model": model, "prompt": "", "keep_alive": "10m"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"✅ Préchargement Ollama {model} déclenché")
                        return True
                    logger.warning(f"Ollama préchargement {model} status {resp.status}")
                    return False
        except Exception as e:
            logger.warning(f"Préchargement {model} échoué: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Retourne l'état courant du guardian (pression, modèles, budget)."""
        return {
            "pressure": self._pressure.value,
            "budget_gb": self._budget_gb,
            "used_gb": round(self._used_budget_gb(), 2),
            "free_gb": round(self._budget_gb - self._used_budget_gb(), 2),
            "models": {
                name: {
                    "size_gb": rec.size_gb,
                    "use_count": rec.use_count,
                    "last_use": rec.last_use,
                    "utility": round(rec.utility(), 4),
                }
                for name, rec in self._loaded_models.items()
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Publication EventBus
    # ─────────────────────────────────────────────────────────────────────────

    async def _publish(self, channel: str, data: Dict[str, Any]) -> None:
        """Publie un événement sur l'EventBus si disponible."""
        if self._event_bus is None or self._token is None:
            return
        try:
            await self._event_bus.publish(
                channel=channel,
                data=data,
                source="memory_guardian",
                token=self._token,
            )
        except Exception as e:
            logger.debug(f"Publish {channel} échoué (non bloquant): {e}")
