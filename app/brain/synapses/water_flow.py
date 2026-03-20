"""
WaterFlow — flux d'information continu entre agents
Loi : moindre action + symbiose
Concept : chaque LLM = grain de sable, l'info coule sans blocage

Chaque agent reçoit le contexte enrichi par le précédent
et ajoute sa couche sans jamais bloquer le flux.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WaterDrop:
    """
    Une goutte d'eau = unité d'information qui traverse le flux.
    Chaque agent l'enrichit avant de la passer au suivant.
    """
    query: str
    context: Dict[str, Any] = field(default_factory=dict)
    enrichments: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    final_response: Optional[str] = None
    total_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def enrich(self, agent_name: str, data: Dict[str, Any]) -> None:
        """Ajoute une couche d'enrichissement au flux."""
        self.enrichments.append({
            "agent": agent_name,
            "data": data,
            "timestamp": time.time(),
        })
        self.context.update(data)

    def add_error(self, agent_name: str, error: str) -> None:
        """Note une erreur sans bloquer le flux."""
        self.errors.append(f"[{agent_name}] {error}")
        logger.warning(f"⚠️ WaterFlow erreur ({agent_name}) : {error}")

    @property
    def enrichment_count(self) -> int:
        return len(self.enrichments)


@dataclass
class WaterGrain:
    """
    Un grain de sable = un agent dans le flux.
    name      : identifiant de l'agent
    handler   : fonction async qui enrichit la goutte
    timeout   : max secondes avant de passer au suivant
    optional  : si True, une erreur ne bloque pas le flux
    """
    name: str
    handler: Callable[[WaterDrop], Any]
    timeout: float = 5.0
    optional: bool = True


class WaterFlow:
    """
    Flux d'information continu multi-agents.

    Usage :
        flow = WaterFlow()
        flow.add_grain("security",  security_handler)
        flow.add_grain("router",    router_handler)
        flow.add_grain("executor",  executor_handler)
        flow.add_grain("memory",    memory_handler)

        drop = await flow.run("ouvre Safari")
        print(drop.final_response)
    """

    def __init__(self) -> None:
        self._grains: List[WaterGrain] = []
        self._stats = {
            "total_runs": 0,
            "completed": 0,
            "errors": 0,
            "avg_ms": 0.0,
        }

    def add_grain(
        self,
        name: str,
        handler: Callable[[WaterDrop], Any],
        timeout: float = 5.0,
        optional: bool = True,
    ) -> "WaterFlow":
        """Ajoute un agent au flux. Retourne self pour chaînage."""
        self._grains.append(WaterGrain(
            name=name,
            handler=handler,
            timeout=timeout,
            optional=optional,
        ))
        logger.debug(f"💧 Grain ajouté : {name}")
        return self

    async def run(self, query: str, initial_context: Optional[Dict] = None) -> WaterDrop:
        """
        Lance le flux pour une requête.
        Chaque grain enrichit la goutte sans bloquer le suivant.
        """
        t0 = time.perf_counter()
        self._stats["total_runs"] += 1

        drop = WaterDrop(
            query=query,
            context=initial_context or {},
        )

        for grain in self._grains:
            await self._pass_through_grain(drop, grain)

        drop.total_ms = (time.perf_counter() - t0) * 1000
        self._stats["completed"] += 1

        # Mise à jour moyenne mobile
        n = self._stats["completed"]
        self._stats["avg_ms"] = (
            (self._stats["avg_ms"] * (n - 1) + drop.total_ms) / n
        )

        logger.info(
            f"💧 Flux terminé : {drop.enrichment_count} enrichissements "
            f"en {drop.total_ms:.1f}ms"
        )
        return drop

    async def _pass_through_grain(self, drop: WaterDrop, grain: WaterGrain) -> None:
        """
        Passe la goutte à travers un grain.
        Timeout + gestion d'erreur sans blocage.
        """
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._call_handler(grain.handler, drop),
                timeout=grain.timeout,
            )
            elapsed = (time.perf_counter() - t0) * 1000

            if result is not None:
                if isinstance(result, dict):
                    drop.enrich(grain.name, result)
                elif isinstance(result, str):
                    drop.enrich(grain.name, {"response": result})
                    if drop.final_response is None:
                        drop.final_response = result

            logger.debug(f"💧 {grain.name} → {elapsed:.1f}ms")

        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - t0) * 1000
            msg = f"Timeout après {elapsed:.0f}ms"
            drop.add_error(grain.name, msg)
            self._stats["errors"] += 1
            # Le flux continue — grain optionnel

        except Exception as e:
            drop.add_error(grain.name, str(e))
            self._stats["errors"] += 1
            if not grain.optional:
                raise

    async def _call_handler(
        self,
        handler: Callable,
        drop: WaterDrop,
    ) -> Any:
        """Appelle le handler (sync ou async)."""
        if asyncio.iscoroutinefunction(handler):
            return await handler(drop)
        else:
            return handler(drop)

    @property
    def grain_count(self) -> int:
        return len(self._grains)

    @property
    def stats(self) -> dict:
        return {**self._stats}


# ── Grains prêts à l'emploi pour Lucie ──────────────────────────────

_threat_intel = None

async def security_grain(drop: WaterDrop) -> Optional[Dict]:
    """Grain 1 — ThreatIntelligence avant tout traitement."""
    try:
        global _threat_intel
        if _threat_intel is None:
            from app.security.threat_intelligence import ThreatIntelligence
            _threat_intel = ThreatIntelligence()
        report = _threat_intel.analyze(drop.query)
        if report.blocked:
            drop.final_response = (
                f"⚠️ Requête bloquée pour sécurité : {report.reason}"
            )
            return {"blocked": True, "reason": report.reason}
        return {"blocked": False, "threat_level": report.level.value}
    except Exception as e:
        return {"blocked": False, "security_error": str(e)}


_router_singleton = None

async def router_grain(drop: WaterDrop) -> Optional[Dict]:
    """Grain 2 — Fast Path routing (singleton — init une seule fois)."""
    if drop.context.get("blocked"):
        return None
    global _router_singleton
    try:
        from app.brain.cortex.router import PathRouter
        if _router_singleton is None:
            _router_singleton = PathRouter()
            _router_singleton.initialize()
        router = _router_singleton
        result = router.route(drop.query)
        return {
            "agent": result.agent,
            "confidence": result.confidence,
            "via_fast_path": result.via_fast_path,
        }
    except Exception as e:
        return {"agent": "fallback", "router_error": str(e)}


_memory_singleton = None

async def memory_grain(drop: WaterDrop) -> Optional[Dict]:
    """Grain 3 — Enrichit avec la mémoire épisodique."""
    if drop.context.get("blocked"):
        return None
    try:
        global _memory_singleton
        if _memory_singleton is None:
            from app.memory.episodic_memory import EpisodicMemory
            _memory_singleton = EpisodicMemory()
        memory = _memory_singleton
        # Cherche les 3 dernières interactions similaires
        recent = await memory.search_async(drop.query, limit=3) \
            if hasattr(memory, 'search_async') else []
        return {"recent_context": recent[:3] if recent else []}
    except Exception:
        return {"recent_context": []}


async def logger_grain(drop: WaterDrop) -> Optional[Dict]:
    """Grain 4 — CodeLogger pour le Self-Healing (Bloc 5b)."""
    try:
        import json
        from pathlib import Path
        log_path = Path("memory/journals/machine_log.jsonl")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "query": drop.query[:80],
            "agent": drop.context.get("agent", "unknown"),
            "fast_path": drop.context.get("via_fast_path", False),
            "enrichments": drop.enrichment_count,
            "errors": drop.errors,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"logged": True}
    except Exception as e:
        return {"logged": False, "log_error": str(e)}
