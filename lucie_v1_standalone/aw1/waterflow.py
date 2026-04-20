"""
WaterFlow — pipeline d'information multi-stages configurable à chaud.

Concept : chaque agent = grain de sable, l'info coule sans blocage.
Chaque agent reçoit le contexte enrichi par le précédent
et ajoute sa couche sans jamais bloquer le flux.

Salvagé depuis archive/pre-cleanup:app/brain/synapses/water_flow.py.
Grains prêts-à-l'emploi legacy (security_grain, router_grain, memory_grain,
logger_grain) retirés — ils référençaient des modules supprimés lors
de la chirurgie du 16 avril 2026.

Usage :
    flow = WaterFlow()
    flow.add_grain("etape_a", handler_a, stage=0)
    flow.add_grain("etape_b", handler_b, stage=0)  # parallèle avec etape_a
    flow.add_grain("etape_c", handler_c, stage=1)  # après stage 0

    drop = await flow.run("ma requête")
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
    Unité d'information qui traverse le flux.
    Chaque grain l'enrichit avant de la passer au suivant.
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
        logger.warning("WaterFlow erreur (%s) : %s", agent_name, error)

    @property
    def enrichment_count(self) -> int:
        return len(self.enrichments)


@dataclass
class WaterGrain:
    """
    Un agent dans le flux.
    name    : identifiant de l'agent
    handler : fonction (sync ou async) qui enrichit la goutte
    timeout : secondes max avant de passer au suivant
    optional: si True, une erreur ne bloque pas le flux
    stage   : grains de même stage s'exécutent en parallèle
    """
    name: str
    handler: Callable[[WaterDrop], Any]
    timeout: float = 5.0
    optional: bool = True
    stage: int = 0


class WaterFlow:
    """
    Pipeline d'information continu multi-agents.

    Les grains sont groupés par stage ; les grains d'un même stage
    s'exécutent en parallèle (asyncio.gather). Fallback séquentiel
    si gather échoue.
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
        stage: int = 0,
    ) -> "WaterFlow":
        """Ajoute un grain au flux. Retourne self pour chaînage."""
        self._grains.append(WaterGrain(
            name=name,
            handler=handler,
            timeout=timeout,
            optional=optional,
            stage=stage,
        ))
        return self

    async def run(
        self,
        query: str,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> WaterDrop:
        """
        Lance le flux pour une requête.
        Grains groupés par stage — même stage = exécution parallèle.
        """
        t0 = time.perf_counter()
        self._stats["total_runs"] += 1

        drop = WaterDrop(query=query, context=initial_context or {})

        stages: Dict[int, List[WaterGrain]] = {}
        for grain in self._grains:
            stages.setdefault(grain.stage, []).append(grain)

        for stage_id in sorted(stages.keys()):
            grains_in_stage = stages[stage_id]

            if len(grains_in_stage) == 1:
                await self._pass_through_grain(drop, grains_in_stage[0])
            else:
                try:
                    tasks = [
                        self._pass_through_grain(drop, g)
                        for g in grains_in_stage
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)
                except Exception as exc:
                    # Fallback séquentiel si gather échoue
                    logger.warning("WaterFlow fallback séquentiel stage %d : %s", stage_id, exc)
                    for g in grains_in_stage:
                        await self._pass_through_grain(drop, g)

        drop.total_ms = (time.perf_counter() - t0) * 1000
        self._stats["completed"] += 1

        n = self._stats["completed"]
        self._stats["avg_ms"] = (
            (self._stats["avg_ms"] * (n - 1) + drop.total_ms) / n
        )

        logger.debug(
            "WaterFlow terminé : %d enrichissements en %.1fms",
            drop.enrichment_count, drop.total_ms,
        )
        return drop

    async def _pass_through_grain(self, drop: WaterDrop, grain: WaterGrain) -> None:
        """Passe la goutte à travers un grain. Timeout + gestion d'erreur."""
        try:
            result = await asyncio.wait_for(
                self._call_handler(grain.handler, drop),
                timeout=grain.timeout,
            )

            if result is not None:
                if isinstance(result, dict):
                    drop.enrich(grain.name, result)
                elif isinstance(result, str):
                    drop.enrich(grain.name, {"response": result})
                    if drop.final_response is None:
                        drop.final_response = result

        except asyncio.TimeoutError:
            drop.add_error(grain.name, f"Timeout après {grain.timeout:.0f}s")
            self._stats["errors"] += 1

        except Exception as exc:
            drop.add_error(grain.name, str(exc))
            self._stats["errors"] += 1
            if not grain.optional:
                raise

    async def _call_handler(
        self,
        handler: Callable[[WaterDrop], Any],
        drop: WaterDrop,
    ) -> Any:
        """Appelle le handler (sync ou async)."""
        if asyncio.iscoroutinefunction(handler):
            return await handler(drop)
        return handler(drop)

    @property
    def grain_count(self) -> int:
        return len(self._grains)

    @property
    def stats(self) -> Dict[str, Any]:
        return {**self._stats}
