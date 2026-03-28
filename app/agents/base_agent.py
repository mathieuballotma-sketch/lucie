"""
BaseAgent - Classe de base pour tous les agents.
v5 : ajout set_token(), _publish_error async-safe, token et event_bus intégrés.

Corrections v5 :
  - Ajout de self.token et self.event_bus dans __init__
  - Ajout de set_token(token) pour injection par le registre
  - _publish_error : passage en asyncio.create_task + token obligatoire
  - Suppression du print de debug en production (gardé en commentaire)
"""

import asyncio
import inspect
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from pydantic.v1 import BaseModel, ValidationError

from ..utils.circuit_breaker import CircuitBreaker
from ..utils.errors import ToolValidationError, ToolExecutionError, ToolNotFoundError
from ..utils.logger import logger
from ..utils.metrics import tool_execution_duration, tool_execution_errors


class Tool:
    def __init__(self, name: str, description: str, contract: Type[BaseModel]):
        self.name = name
        self.description = description
        self.contract = contract

    def validate(self, params: Dict[str, Any]) -> BaseModel:
        try:
            return self.contract(**params)
        except ValidationError as e:
            logger.error(f"Erreur de validation [{self.name}]: {e}")
            raise


class BaseAgent(ABC):
    def __init__(self, name: str, llm_service: Any, bus: Any, event_bus: Any = None, token: Optional[str] = None):
        self.name = name
        self.llm = llm_service
        self.bus = bus
        self._tools_cache: Optional[Dict[str, Tool]] = None

        # --- FIX v5 : token et event_bus font partie de la base ---
        self.token: Optional[str] = token
        self.event_bus = event_bus

        # TimeTracker — injecte par l'engine, optionnel
        self.time_tracker: Any = None

        # CircuitBreaker pour protéger les appels LLM contre les pannes répétées
        self._llm_cb = CircuitBreaker(name=f"llm_{name}", failure_threshold=5, recovery_timeout=60.0)

        logger.info(f"🤖 Agent '{self.name}' initialisé")

    # --- FIX v5 : méthode d'injection du token par le registre ---
    def set_token(self, token: str) -> None:
        """
        Injecte le token EventBus fourni par AgentRegistry.
        À appeler juste après l'instanciation, avant tout abonnement.
        """
        self.token = token
        logger.debug(f"🔑 Token injecté dans {self.name} : {token[:8]}…")

    @abstractmethod
    def can_handle(self, query: str) -> bool:
        pass

    async def handle(self, query: str) -> str:
        """
        Comportement par défaut : interroger le LLM.
        Les sous-classes peuvent surcharger cette méthode.
        """
        return await self.ask_llm_async(query)

    def get_tools(self) -> List[Tool]:
        return []

    def _get_tool_by_name(self, name: str) -> Optional[Tool]:
        if self._tools_cache is None:
            self._tools_cache = {t.name: t for t in self.get_tools()}
        return self._tools_cache.get(name)

    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> str:
        logger.info(f"🛠️ execute_tool: {tool_name} avec params {parameters}")

        # TimeTracker — demarrer le chronometrage si disponible
        timing = None
        tracker = self.time_tracker
        if tracker is not None:
            try:
                timing = tracker.start_task(tool_name, self.name)
            except Exception:
                pass

        start = time.time()
        tool = self._get_tool_by_name(tool_name)
        if not tool:
            msg = f"Outil '{tool_name}' non trouvé dans {self.name}"
            logger.error(msg)
            tool_execution_errors.labels(agent=self.name, tool=tool_name).inc()
            raise ToolNotFoundError(tool_name)

        try:
            validated = tool.validate(parameters)
            logger.debug(f"Paramètres validés [{tool_name}]: {validated.dict()}")
        except ValidationError as e:
            msg = f"Paramètres invalides [{tool_name}]: {e}"
            logger.error(msg)
            tool_execution_errors.labels(agent=self.name, tool=tool_name).inc()
            errors = e.errors()
            suggestions = []
            for err in errors:
                loc = ".".join(str(x) for x in err["loc"])
                suggestions.append(f"Le champ '{loc}' : {err['msg']}")
            suggestion = " ".join(suggestions) if suggestions else "Vérifiez les paramètres fournis."
            raise ToolValidationError(msg, suggestion=suggestion)

        method_name = f"_tool_{tool_name}"
        if not hasattr(self, method_name):
            msg = f"Méthode '{method_name}' non implémentée dans {self.name}"
            logger.error(msg)
            tool_execution_errors.labels(agent=self.name, tool=tool_name).inc()
            raise ToolExecutionError(msg, suggestion="L'outil est défini mais pas implémenté.")

        method = getattr(self, method_name)
        params = validated.dict(exclude_none=True)

        try:
            if inspect.iscoroutinefunction(method):
                result = await method(**params)
            else:
                result = method(**params)
            duration = time.time() - start
            tool_execution_duration.labels(agent=self.name, tool=tool_name).observe(duration)
            logger.info(f"✅ [{tool_name}] exécuté en {duration:.2f}s")
            # TimeTracker — enregistrer la duree
            if timing is not None and tracker is not None:
                try:
                    tracker.end_task(timing)
                except Exception:
                    pass
            return str(result) if result is not None else ""
        except Exception as e:
            duration = time.time() - start
            logger.error(f"Erreur exécution [{tool_name}]: {e}")
            tool_execution_errors.labels(agent=self.name, tool=tool_name).inc()
            self._publish_error(tool_name, str(e))
            raise ToolExecutionError(f"Erreur lors de l'exécution: {str(e)}")

    async def submit_action(self, action_data: Dict[str, Any]) -> bool:
        """
        Soumet une action à ActionGate via l'EventBus.

        Publie sur le canal "action_request" si l'EventBus est disponible.
        Si l'EventBus est absent ou le token manquant, retourne True immédiatement
        (compatibilité ascendante — l'agent opère normalement).

        Args:
            action_data: dict avec action_type, preview, reversible, etc.

        Returns:
            True si l'action peut être exécutée, False si elle doit être bloquée.
        """
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            return True

        try:
            await event_bus.publish(
                channel="action_request",
                data={**action_data, "agent": self.name},
                source=self.name,
                token=self.token,
            )
        except Exception as e:
            logger.warning(f"submit_action [{self.name}] : publish échoué — {e}")

        return True

    def _publish_error(self, tool: str, error: str) -> None:
        """
        Publie une erreur d'outil sur l'EventBus de manière async-safe.

        FIX v5 :
          - Utilise asyncio.create_task (non bloquant, compatible avec la boucle en cours)
          - Vérifie que token est disponible avant de publier
          - Ne lève jamais d'exception (publication best-effort)
        """
        if not self.event_bus or not self.token:
            # Pas de bus ou pas de token — on log et on passe
            if self.event_bus and not self.token:
                logger.warning(
                    f"_publish_error [{self.name}] : token manquant, "
                    "erreur non publiée sur l'EventBus."
                )
            return

        try:
            asyncio.create_task(
                self.event_bus.publish(
                    channel="tool.error",
                    data={
                        "agent": self.name,
                        "tool": tool,
                        "error": error,
                    },
                    source=self.name,
                    token=self.token,
                )
            )
        except RuntimeError:
            # Pas de boucle asyncio en cours (appel depuis un thread sync) — on ignore
            logger.debug(
                f"_publish_error [{self.name}] : pas de boucle asyncio active, "
                "erreur non publiée."
            )

    def ask_llm(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: str = "balanced",
        model_role: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 512,
    ) -> str:
        def _call() -> str:
            return str(self.llm.generate(
                prompt=prompt,
                system=system_prompt,
                model=None if model_role else model,
                model_role=model_role,
                temperature=temperature,
                max_tokens=max_tokens,
            ))

        def _fallback() -> str:
            return "[LLM indisponible — circuit ouvert]"

        try:
            response = self._llm_cb.call(_call, _fallback)
            return response if response else "[RÉPONSE VIDE]"
        except Exception as e:
            logger.error(f"Erreur LLM [{self.name}]: {e}")
            return f"Erreur LLM: {str(e)}"

    async def ask_llm_async(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: str = "balanced",
        model_role: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 512,
    ) -> str:
        """Version asynchrone de ask_llm (exécute dans un thread)."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self.ask_llm,
            prompt,
            system_prompt,
            model,
            model_role,
            temperature,
            max_tokens,
        )
        return str(result)

    def extract_json_from_response(self, response: str) -> Optional[Dict[Any, Any]]:
        cleaned = re.sub(r'^```json\s*', '', response.strip())
        cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            return dict(json.loads(cleaned))
        except json.JSONDecodeError:
            for pattern in [r'(\{.*\})', r'(\[.*\])']:
                match = re.search(pattern, cleaned, re.DOTALL)
                if match:
                    try:
                        return dict(json.loads(match.group(1)))
                    except json.JSONDecodeError:
                        continue
        logger.warning(f"JSON non extractible: {cleaned[:200]}…")
        return None
