"""
Planner Agent - Planifie et exécute des tâches complexes en plusieurs étapes.
Version améliorée avec gestion des dépendances, exécution parallèle, et robustesse.
Incarne les principes :
- Moindre action : parallélisation, timeouts adaptatifs.
- Homéostasie : gestion d'erreurs robuste, publication sur event bus.
- Évolution : métriques pour l'auto-amélioration.
- Symbiose : intégration avec les autres agents via leurs outils.
"""

import asyncio
import json
import time
from typing import Dict, List, Any, Optional, Set
from pydantic.v1 import BaseModel, Field, validator

from app.agents.base_agent import BaseAgent, Tool
from app.providers.manager import ProviderManager
from app.brain.synapses.event_bus import EventBus
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError
from app.utils.circuit_breaker import CircuitBreaker, CircuitState


# ---------------------------------------------------------------------1--
# Exceptions personnalisées
# -----------------------------------------------------------------------
class PlanError(Exception):
    """Erreur de base pour PlannerAgent."""
    pass


class PlanCreationError(PlanError):
    """Erreur lors de la création du plan."""
    pass


class StepExecutionError(PlanError):
    """Erreur lors de l'exécution d'une étape."""
    pass


# -----------------------------------------------------------------------
# Modèles Pydantic
# -----------------------------------------------------------------------
class PlanStep(BaseModel):
    id: str = Field(..., description="Identifiant unique de l'étape")
    agent: str = Field(..., description="Nom de l'agent à utiliser")
    tool: str = Field(..., description="Nom de l'outil à exécuter")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Paramètres de l'outil")
    description: str = Field(..., description="Description de l'étape")
    depends_on: Optional[List[str]] = Field(None, description="IDs des étapes dont dépend cette étape")

    @validator('id')
    def id_non_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("L'id ne peut pas être vide")
        return v

    @validator('agent')
    def agent_non_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("L'agent ne peut pas être vide")
        return v


# -----------------------------------------------------------------------
# Agent planificateur
# -----------------------------------------------------------------------
class PlannerAgent(BaseAgent):
    """
    Agent capable de décomposer une requête complexe en un plan d'actions,
    et d'exécuter les étapes en respectant les dépendances (parallélisme possible).
    """

    def __init__(
        self,
        llm_service: ProviderManager,
        bus: Any,
        event_bus: EventBus,
        config: dict
    ):
        super().__init__("PlannerAgent", llm_service, bus)
        self.event_bus = event_bus
        self.agents: Dict[str, BaseAgent] = {}  # Sera injecté par le cortex

        # Configuration
        self.max_steps = config.get("max_plan_steps", 5)
        self.max_parallel_workers = config.get("max_parallel_workers", 3)
        self.stop_on_error = config.get("stop_on_error", False)
        self.plan_timeout = config.get("plan_timeout", 30.0)
        self.plan_model = config.get("plan_model", "balanced")
        self.plan_fallback_model = config.get("plan_fallback_model", "speed")

        # Circuit breaker pour les appels LLM
        self.circuit_breaker = CircuitBreaker(
            name="planner_llm",
            failure_threshold=config.get("cb_failure_threshold", 3),
            recovery_timeout=config.get("cb_recovery_timeout", 60)
        ) if config.get("enable_circuit_breaker", True) else None

        # Métriques

        logger.info(f"📋 PlannerAgent initialisé (max_steps={self.max_steps}, workers={self.max_parallel_workers})")

    def set_agents(self, agents: Dict[str, BaseAgent]):
        """Injecte la liste des agents disponibles."""
        self.agents = agents

    def get_tools(self) -> list:
        return []  # PlannerAgent n'expose pas d'outils directement

    async def create_plan(self, query: str) -> List[PlanStep]:
        """
        Utilise le LLM pour générer un plan d'actions.
        Retourne une liste d'étapes, ou [] si impossible.
        Lève PlanCreationError en cas d'échec grave.
        """
        start_time = time.time()

        agents_desc = "\n".join(
            f"- {name}: {', '.join(t.name for t in agent.get_tools())}"
            for name, agent in self.agents.items()
        )
        prompt = f"""Tu es un planificateur d'actions. Pour la requête : "{query}", génère une liste d'étapes sous forme de JSON.

Agents disponibles :
{agents_desc}

Chaque étape doit avoir :
- id: string (ex: "1", "2")
- agent: nom de l'agent
- tool: nom de l'outil
- parameters: dictionnaire des paramètres (optionnel)
- description: description de l'étape
- depends_on: liste des IDs des étapes dont dépend cette étape (optionnel)

Réponds UNIQUEMENT avec le JSON, sous forme d'une liste. Exemple :
[
  {{
    "id": "1",
    "agent": "ComputerControlAgent",
    "tool": "open_application",
    "parameters": {{"app_name": "Notes"}},
    "description": "Ouvrir l'application Notes"
  }},
  {{
    "id": "2",
    "agent": "ComputerControlAgent",
    "tool": "type_text",
    "parameters": {{"text": "Bonjour"}},
    "description": "Taper le texte",
    "depends_on": ["1"]
  }}
]
Si la requête ne nécessite qu'une seule étape, retourne une liste avec un seul élément.
Si la requête est impossible à planifier, retourne [].
"""
        try:
            # Appel LLM avec circuit breaker et timeout
            model_name = self.plan_model
            if self.circuit_breaker:
                response = await self._call_llm_with_cb(prompt, model_name)
            else:
                response = await self._call_llm(prompt, model_name)

            if not response:
                # Fallback sur le modèle plus petit
                logger.warning("Fallback sur le modèle speed pour la création du plan")
                response = await self._call_llm(prompt, self.plan_fallback_model)

            if response is None:
                raise ValueError("Aucune réponse du LLM après fallback")
            cleaned = response.strip()
            # Nettoyer les éventuels blocs markdown
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            if not isinstance(data, list):
                logger.error(f"La réponse du planner n'est pas une liste: {data}")
                return []

            # Valider chaque étape avec Pydantic
            steps = []
            for item in data:
                try:
                    step = PlanStep(**item)
                    # Vérification supplémentaire : l'agent existe-t-il ?
                    if step.agent not in self.agents:
                        logger.warning(f"Agent {step.agent} inconnu dans l'étape {step.id}, on garde quand même (sera détecté à l'exécution)")
                    steps.append(step)
                except Exception as e:
                    logger.error(f"Étape invalide ignorée: {item} - {e}")

            if len(steps) > self.max_steps:
                logger.warning(f"Plan trop long ({len(steps)} > {self.max_steps}), troncature")
                steps = steps[:self.max_steps]

            duration = time.time() - start_time
            
            logger.info(f"Plan créé avec {len(steps)} étapes en {duration:.2f}s")
            return steps

        except json.JSONDecodeError as e:
            logger.error(f"Erreur de parsing JSON: {e}")
            await self.event_bus.publish("tool.error", {
                "agent": self.name,
                "error": f"Plan creation failed: invalid JSON - {e}",
                "suggestion": "Le LLM a généré une réponse mal formée. Réessayez ou reformulez."
            })
            return []
        except asyncio.TimeoutError:
            logger.error("Timeout lors de la création du plan")
            await self.event_bus.publish("tool.error", {
                "agent": self.name,
                "error": "Plan creation timeout",
                "suggestion": "Le modèle a mis trop de temps à répondre. Réessayez plus tard."
            })
            return []
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la création du plan: {e}")
            await self.event_bus.publish("tool.error", {
                "agent": self.name,
                "error": f"Unexpected error: {e}",
                "suggestion": "Vérifiez les logs pour plus de détails."
            })
            return []

    async def _call_llm(self, prompt: str, model: str) -> Optional[str]:
        """Appelle le LLM avec timeout."""
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            None,
            lambda: self.llm.generate(
                prompt=prompt,
                system="",
                model=model,
                temperature=0.3,
                max_tokens=1024,
                timeout=self.plan_timeout
            )
        )
        return await asyncio.wait_for(future, timeout=self.plan_timeout + 2.0)

    async def _call_llm_with_cb(self, prompt: str, model: str) -> Optional[str]:
        """Appelle le LLM avec vérification circuit breaker (async-compatible)."""
        cb = self.circuit_breaker
        if cb is None:
            return await self._call_llm(prompt, model)
        # Vérifier si le circuit est ouvert avant d'appeler
        if cb.state == CircuitState.OPEN:
            elapsed = time.time() - cb.last_failure_time
            if elapsed < cb.recovery_timeout:
                logger.warning(f"Circuit '{cb.name}' ouvert, skip appel LLM")
                return None
        try:
            result = await self._call_llm(prompt, model)
            # Enregistrer le succès dans le circuit breaker
            with cb._lock:
                cb.metrics.successful_calls += 1
                cb.metrics.total_calls += 1
                cb.failure_count = 0
            return result
        except Exception as e:
            # Enregistrer l'échec
            with cb._lock:
                cb.metrics.failed_calls += 1
                cb.metrics.total_calls += 1
                cb.failure_count += 1
                cb.last_failure_time = time.time()
                if cb.failure_count >= cb.failure_threshold:
                    cb._transition_to(CircuitState.OPEN)
            logger.error(f"Circuit breaker échec: {e}")
            return None

    async def execute_plan(self, steps: List[PlanStep]) -> str:
        """
        Exécute un plan en respectant les dépendances.
        Les étapes indépendantes sont exécutées en parallèle.
        Retourne un résumé des résultats.
        """
        if not steps:
            return "Aucune étape à exécuter."
        start_time = time.time()

        # Construire un graphe de dépendances
        step_dict = {step.id: step for step in steps}
        dependents: Dict[str, List[str]] = {step.id: [] for step in steps}
        dependencies_count: Dict[str, int] = {step.id: 0 for step in steps}

        for step in steps:
            if step.depends_on:
                for dep_id in step.depends_on:
                    if dep_id in step_dict:
                        dependents[dep_id].append(step.id)
                        dependencies_count[step.id] += 1
                    else:
                        logger.warning(f"Étape {step.id} dépend d'une étape inconnue {dep_id}, ignorée")

        # File d'attente des étapes prêtes
        ready = asyncio.Queue()
        for step_id, count in dependencies_count.items():
            if count == 0:
                await ready.put(step_id)

        results: Dict[str, str] = {}
        errors: Dict[str, str] = {}
        cancelled = False

        async def worker(worker_id: int):
            nonlocal cancelled
            while not cancelled:
                try:
                    step_id = await asyncio.wait_for(ready.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    # Vérifier si tout est terminé
                    if ready.empty() and len(results) + len(errors) == len(step_dict):
                        break
                    continue

                if cancelled:
                    # Si annulé, on remet l'étape dans la file ? Non, on abandonne.
                    continue

                step = step_dict[step_id]
                agent = self.agents.get(step.agent)
                if not agent:
                    error_msg = f"❌ Étape {step.id}: Agent {step.agent} introuvable"
                    logger.error(error_msg)
                    errors[step_id] = error_msg
                    await self.event_bus.publish("tool.error", {
                        "agent": self.name,
                        "step_id": step.id,
                        "error": f"Agent {step.agent} not found",
                        "suggestion": "Vérifiez que l'agent est bien enregistré."
                    })
                    # Libérer les dépendants même en cas d'échec ? Oui, car ils ne pourront pas s'exécuter si stop_on_error est False.
                    # Mais si stop_on_error est True, on annule tout.
                    if self.stop_on_error:
                        cancelled = True
                        # On vide la queue
                        while not ready.empty():
                            try:
                                ready.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        break
                else:
                    try:
                        logger.info(f"🧑‍🏭 Worker {worker_id} exécute étape {step.id}: {step.description}")
                        result = await agent.execute_tool(step.tool, step.parameters)
                        results[step_id] = f"✅ Étape {step.id}: {result}"
                    except Exception as e:
                        error_msg = f"❌ Étape {step.id} échouée: {e}"
                        logger.error(error_msg)
                        errors[step_id] = error_msg
                        await self.event_bus.publish("tool.error", {
                            "agent": self.name,
                            "step_id": step.id,
                            "error": str(e),
                            "suggestion": "Consultez les logs pour plus de détails."
                        })
                        if self.stop_on_error:
                            cancelled = True
                            # Vider la queue
                            while not ready.empty():
                                try:
                                    ready.get_nowait()
                                except asyncio.QueueEmpty:
                                    break
                            break

                # Libérer les dépendants
                for dep_id in dependents[step_id]:
                    dependencies_count[dep_id] -= 1
                    if dependencies_count[dep_id] == 0:
                        await ready.put(dep_id)

        # Lancer les workers
        workers = [
            asyncio.create_task(worker(i))
            for i in range(min(self.max_parallel_workers, len(steps)))
        ]
        await asyncio.gather(*workers, return_exceptions=True)

        duration = time.time() - start_time
        

        # Construire la réponse finale
        output = []
        for step in steps:
            if step.id in results:
                output.append(results[step.id])
            elif step.id in errors:
                output.append(errors[step.id])
        if errors and not self.stop_on_error:
            output.append("⚠️ Certaines étapes ont échoué, mais le plan a continué.")
        elif cancelled:
            output.append("⛔ Plan arrêté en raison d'une erreur.")
        logger.info(f"Plan exécuté en {duration:.2f}s, {len(results)} succès, {len(errors)} échecs")
        return "\n".join(output) if output else "Aucun résultat."

    async def stop(self):
        """Arrête proprement l'agent (rien de spécial pour l'instant)."""
        logger.info("📋 PlannerAgent arrêté.")
    def can_handle(self, query: str) -> bool:
        """Le planner gère les requêtes multi-étapes complexes."""
        keywords = ["puis", "ensuite", "après", "étape", "d'abord", "enfin", "plan"]
        return any(kw in query.lower() for kw in keywords)
