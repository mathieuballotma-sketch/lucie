"""
Creator Agent — Génère de nouveaux agents à partir d'une description.

Corrections v3 :
  - MetricsCollector supprimé → dict interne _stats pour comptage léger
  - CircuitBreaker.call_async supprimé → circuit_breaker.call() synchrone
    wrappé dans run_in_executor (seule API disponible dans circuit_breaker.py)
  - agent_class(config={}) supprimé → BaseAgent.__init__ n'a pas de paramètre config
  - publish sur None corrigé → variable locale 'event_bus' pour type-narrowing Pylance
  - token vérifié et passé à tous les publish()

Principes :
  • Homéostasie  : validation + tests du code généré
  • Évolution    : apprentissage par les échecs
  • Symbiose     : notifications via event bus
  • Moindre action : retries intelligents, prompts ciblés
"""

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import ast
import threading

from pydantic.v1 import BaseModel, Field, validator

from app.agents.base_agent import BaseAgent, Tool
from app.providers.manager import ProviderManager
from app.brain.synapses.event_bus import EventBus
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError
from app.utils.circuit_breaker import CircuitBreaker


# Timeout d'exécution pour le sandbox exec() — évite les boucles infinies et le code bloquant
_EXEC_TIMEOUT: float = 5.0

# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────
class AgentCreationError(Exception):
    """Erreur lors de la création d'un agent."""


class InvalidAgentCodeError(AgentCreationError):
    """Le code généré est invalide ou dangereux."""


# ─────────────────────────────────────────────────────────────────────────────
# Contrats Pydantic
# ─────────────────────────────────────────────────────────────────────────────
class CreateAgentContract(BaseModel):
    description: str = Field(..., description="Description de l'agent à créer", min_length=5)
    name: Optional[str] = Field(None, description="Nom souhaité (optionnel)")

    @validator("name")
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^[A-Z][a-zA-Z0-9_]*$", v):
            raise ValueError(
                "Le nom doit commencer par une majuscule "
                "et ne contenir que des lettres, chiffres et underscores"
            )
        return v


class ListAgentsContract(BaseModel):
    pass


class DeleteAgentContract(BaseModel):
    name: str = Field(..., description="Nom de l'agent à supprimer")


# ─────────────────────────────────────────────────────────────────────────────
# Validateur de code
# ─────────────────────────────────────────────────────────────────────────────
class AgentCodeValidator:
    """
    Valide le code généré :
    1. Sécurité — imports interdits + attributs dangereux
    2. Fonctionnel — instanciation, get_tools(), handle()
    """

    FORBIDDEN_IMPORTS: Set[str] = {
        "os", "subprocess", "socket", "requests", "urllib",
        "shutil", "tempfile", "ctypes", "importlib",
    }

    FORBIDDEN_BUILTINS: Set[str] = {
        "eval", "exec", "compile", "__import__", "open",
        "breakpoint", "input",
        # Accès au système de types et à l'introspection — vecteurs de bypass sandbox
        "type", "object", "getattr", "setattr", "delattr",
        "globals", "locals", "vars", "dir",
        # Noms dunder non-builtins mais listés de façon défensive
        "__class__", "__init__", "__subclasses__",
    }

    FORBIDDEN_ATTRS: Set[str] = {
        "__subclasses__", "__globals__", "__builtins__",
        "__class__", "__bases__", "__mro__",
        "__reduce__", "__reduce_ex__",
    }

    def __init__(self, allowed_tools: Optional[List[str]] = None):
        self.allowed_tools = allowed_tools or []

    def validate_safety(self, code: str) -> Tuple[bool, Optional[str]]:
        """Analyse statique via AST. Retourne (True, class_name) ou (False, message erreur)."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Erreur de syntaxe : {e}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in self.FORBIDDEN_IMPORTS:
                        return False, f"Import interdit : {alias.name}"

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root in self.FORBIDDEN_IMPORTS:
                        return False, f"Import interdit : {node.module}"
                for alias in node.names:
                    if alias.name in self.FORBIDDEN_BUILTINS:
                        return False, f"Import interdit : {alias.name}"

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.FORBIDDEN_BUILTINS:
                        return False, f"Appel interdit : {node.func.id}()"

            elif isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN_ATTRS:
                    return False, f"Accès à un attribut interdit : {node.attr}"

        # Cherche la classe héritant de BaseAgent
        class_name = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "BaseAgent":
                        class_name = node.name
                        break
            if class_name:
                break

        if not class_name:
            return False, "Aucune classe héritant de BaseAgent trouvée"

        return True, class_name

    async def test_functionality(
        self,
        code: str,
        class_name: str,
        loop: asyncio.AbstractEventLoop,
    ) -> Tuple[bool, Optional[str]]:
        """Teste instanciation, get_tools() et handle() dans un namespace restreint."""
        import builtins as _builtins_module
        safe_builtins = {
            k: v for k, v in vars(_builtins_module).items()
            if k not in self.FORBIDDEN_BUILTINS
        }

        namespace: Dict[str, Any] = {
            "__builtins__": safe_builtins,
            "BaseAgent":    BaseAgent,
            "Tool":         Tool,
            "Optional":     Optional,
            "List":         List,
            "Dict":         Dict,
            "Any":          Any,
        }

        def _run_code() -> Optional[str]:
            """Exécute le code dans un thread dédié avec timeout — évite les boucles infinies."""
            exec_error: list = [None]

            def _exec_target() -> None:
                try:
                    exec(code, namespace)  # noqa: S102
                except Exception as exc:
                    exec_error[0] = str(exc)

            exec_thread = threading.Thread(target=_exec_target, daemon=True)
            exec_thread.start()
            exec_thread.join(_EXEC_TIMEOUT)

            if exec_thread.is_alive():
                return f"Timeout : exécution dépassant {_EXEC_TIMEOUT}s"

            # Supprimer __builtins__ du namespace après exec — bloque l'introspection post-exécution
            namespace.pop("__builtins__", None)

            return exec_error[0]

        try:
            exec_error = await loop.run_in_executor(None, _run_code)
        except Exception as exc:
            return False, f"Exception inattendue : {exc}"

        if exec_error:
            return False, f"Erreur d'exécution : {exec_error}"

        agent_class = namespace.get(class_name)
        if not agent_class:
            return False, f"Classe {class_name} introuvable après exécution"

        if not issubclass(agent_class, BaseAgent):
            return False, f"{class_name} n'hérite pas de BaseAgent"

        # FIX v3 : BaseAgent.__init__ signature = (name, llm_service, bus)
        # Pas de paramètre 'config' dans la base — on passe les minimums requis
        try:
            agent = agent_class(
                name=class_name,
                llm_service=None,
                bus=None,
            )
        except Exception as exc:
            return False, f"Erreur lors de l'instanciation : {exc}"

        try:
            tools = agent.get_tools()
            if not isinstance(tools, list):
                return False, "get_tools() ne retourne pas une liste"
            for tool in tools:
                if not isinstance(tool, Tool):
                    return False, f"Outil invalide : {tool!r}"
                if self.allowed_tools and tool.name not in self.allowed_tools:
                    return False, f"Outil '{tool.name}' non autorisé"
        except Exception as exc:
            return False, f"Erreur dans get_tools() : {exc}"

        try:
            result = agent.handle("test query")
            if asyncio.iscoroutine(result):
                result = await result
            if not isinstance(result, str):
                return False, f"handle() retourne {type(result).__name__} au lieu de str"
        except Exception as exc:
            return False, f"Erreur dans handle() : {exc}"

        return True, None


# ─────────────────────────────────────────────────────────────────────────────
# CreatorAgent
# ─────────────────────────────────────────────────────────────────────────────
class CreatorAgent(BaseAgent):
    """
    Génère, valide et enregistre de nouveaux agents à la volée.
    Pipeline : génération LLM → validation AST → tests → sauvegarde → événement.
    """

    def __init__(
        self,
        llm_service: ProviderManager,
        bus: Any,
        event_bus: EventBus,
        config: dict,
        agents_dir: Path,
        available_tools: Optional[List[str]] = None,
        token: Optional[str] = None,
    ):
        super().__init__(
            name="CreatorAgent",
            llm_service=llm_service,
            bus=bus,
            event_bus=event_bus,
            token=token,
        )

        self.agents_dir = agents_dir
        self.agents_dir.mkdir(parents=True, exist_ok=True)

        self.model_profile       = config.get("creator_model",          "balanced")
        self.fallback_model      = config.get("creator_fallback_model",  "speed")
        self.generation_timeout  = config.get("creator_timeout",         30.0)
        self.max_retries         = config.get("creator_max_retries",     3)
        self.ask_user_on_failure = config.get("ask_user_on_failure",     True)

        # FIX v3 : CircuitBreaker.call() uniquement synchrone — pas de call_async
        self.circuit_breaker: Optional[CircuitBreaker] = (
            CircuitBreaker(name="creator_llm", failure_threshold=3, recovery_timeout=60)
            if config.get("enable_circuit_breaker", True)
            else None
        )

        self._available_tools: List[str] = available_tools or []
        self.validator = AgentCodeValidator(allowed_tools=self._available_tools)

        # Compteurs internes légers (pas de MetricsCollector dans metrics.py)
        self._stats: Dict[str, int] = {
            "attempts": 0, "success": 0, "safety_fail": 0,
            "test_fail": 0, "llm_error": 0, "deleted": 0,
        }

        logger.info(f"🧙 CreatorAgent prêt — agents_dir={self.agents_dir}")

    # ── Outils exposés ────────────────────────────────────────────────────────

    def get_tools(self) -> list:
        return [
            Tool(
                name="create_agent",
                description="Crée un nouvel agent à partir d'une description",
                contract=CreateAgentContract,
            ),
            Tool(
                name="list_agents",
                description="Liste tous les agents créés",
                contract=ListAgentsContract,
            ),
            Tool(
                name="delete_agent",
                description="Supprime un agent créé",
                contract=DeleteAgentContract,
            ),
        ]

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(t in q for t in [
            "crée un agent", "créer un agent",
            "génère un agent", "fabrique un agent", "nouvel agent",
        ])

    # ── Génération ────────────────────────────────────────────────────────────

    async def _generate_agent_code(
        self,
        description: str,
        name: Optional[str],
        attempt: int,
        previous_error: Optional[str],
    ) -> Optional[str]:
        """
        Génère le code Python via le LLM.

        FIX v3 : CircuitBreaker n'a que call() synchrone.
        On exécute llm.generate() dans un executor, protégé par circuit_breaker.call()
        si activé — les deux sont synchrones, donc compatibles.
        """
        tools_str = ", ".join(self._available_tools) if self._available_tools else "aucun outil connu"
        model     = self.model_profile if attempt == 0 else self.fallback_model

        prompt = f"""Tu es un générateur de code pour des agents IA.
L'utilisateur veut créer un agent capable de :
{description}

Génère une classe Python complète héritant de `BaseAgent` avec :
- `get_tools()` → liste d'outils parmi : {tools_str}
- `handle(self, query: str) -> str` → logique de l'agent

Règles :
- Nom de classe : {"utilise " + name if name else "invente un nom pertinent (ex: WeatherAgent)"}
- Docstrings obligatoires
- Imports depuis app.agents.base_agent uniquement
- Réponds UNIQUEMENT avec le code Python, sans texte autour
"""
        if previous_error:
            prompt += f"\n\nLa tentative précédente a échoué : {previous_error}\nCorrige précisément cette erreur."

        def _call_llm() -> str:
            """Appel LLM synchrone — compatible avec CircuitBreaker.call()."""
            return self.llm.generate(
                prompt=prompt,
                system="",
                model=model,
                temperature=0.2,
                max_tokens=1500,
                timeout=self.generation_timeout,
            )

        loop = asyncio.get_running_loop()
        try:
            if self.circuit_breaker:
                # circuit_breaker.call() est synchrone → run_in_executor
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self.circuit_breaker.call(_call_llm),  # type: ignore[union-attr]
                    ),
                    timeout=self.generation_timeout + 5.0,
                )
            else:
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, _call_llm),
                    timeout=self.generation_timeout + 5.0,
                )
        except asyncio.TimeoutError:
            logger.error(f"Timeout LLM (tentative {attempt + 1})")
            self._stats["llm_error"] += 1
            return None
        except Exception as exc:
            logger.error(f"Erreur LLM : {exc}")
            self._stats["llm_error"] += 1
            return None

        code = response.strip()
        for fence in ("```python", "```"):
            if code.startswith(fence):
                code = code[len(fence):]
        if code.endswith("```"):
            code = code[:-3]
        return code.strip()

    # ── Notifications ─────────────────────────────────────────────────────────

    async def _notify_user(self, message: str, code: Optional[str] = None) -> bool:
        """
        Publie une notification sur l'event bus.
        FIX v3 : variable locale event_bus → type-narrowing Pylance.
        """
        logger.warning(f"👤 Notification : {message}")

        event_bus = self.event_bus  # type-narrowing
        if event_bus is None or not self.token:
            logger.error("CreatorAgent._notify_user : event_bus ou token manquant.")
            return False

        try:
            await event_bus.publish(
                channel="user.notification",
                data={
                    "level":   "warning",
                    "message": message,
                    "code":    code,
                    "source":  self.name,
                },
                source=self.name,
                token=self.token,
            )
        except Exception as e:
            logger.error(f"CreatorAgent._notify_user erreur : {e}")

        return False

    # ── Pipeline de création ──────────────────────────────────────────────────

    async def _tool_create_agent(
        self,
        description: str,
        name: Optional[str] = None,
    ) -> str:
        """Pipeline complet : génération → validation → test → sauvegarde → événement."""
        last_error: Optional[str] = None

        for attempt in range(self.max_retries + 1):
            self._stats["attempts"] += 1
            logger.info(f"🧙 Tentative {attempt + 1}/{self.max_retries + 1}")

            # 1 — Génération
            code = await self._generate_agent_code(description, name, attempt, last_error)
            if not code:
                last_error = "Échec de génération du code"
                continue

            # 2 — Sécurité
            safe, result = self.validator.validate_safety(code)
            if not safe:
                last_error = f"Sécurité : {result}"
                logger.warning(last_error)
                self._stats["safety_fail"] += 1
                continue

            class_name: str = result  # type: ignore[assignment]

            # 3 — Unicité
            filepath = self.agents_dir / f"{class_name.lower()}.py"
            if filepath.exists():
                last_error = f"Un agent '{class_name}' existe déjà"
                logger.warning(last_error)
                name = f"{class_name}_{attempt + 2}"
                continue

            # 4 — Tests fonctionnels
            loop = asyncio.get_running_loop()
            ok, test_error = await self.validator.test_functionality(code, class_name, loop)
            if not ok:
                last_error = f"Tests : {test_error}"
                logger.warning(last_error)
                self._stats["test_fail"] += 1
                continue

            # 5 — Sauvegarde (avec contrôle ActionGate niveau 3 HIGH)
            approved = await self.submit_action({
                "action_type": "create_agent",
                "preview": f"create_agent: {class_name} → {filepath}",
                "reversible": True,
            })
            if not approved:
                raise ToolExecutionError(f"Création de '{class_name}' bloquée par ActionGate.")
            try:
                filepath.write_text(code, encoding="utf-8")
                logger.info(f"✅ Agent '{class_name}' sauvegardé → {filepath}")
                self._stats["success"] += 1
            except IOError as exc:
                raise ToolExecutionError(f"Impossible d'écrire {filepath} : {exc}") from exc

            # 6 — Événement
            # FIX v3 : variable locale event_bus → type-narrowing Pylance
            event_bus = self.event_bus
            if event_bus is not None and self.token:
                try:
                    await event_bus.publish(
                        channel="agent.created",
                        data={"name": class_name, "path": str(filepath)},
                        source=self.name,
                        token=self.token,
                    )
                except Exception as e:
                    logger.error(f"CreatorAgent : publish agent.created échoué : {e}")
            else:
                logger.warning("CreatorAgent : token manquant — événement agent.created non publié.")

            return f"✅ Agent '{class_name}' créé avec succès."

        # Toutes les tentatives ont échoué
        if self.ask_user_on_failure:
            await self._notify_user(
                f"Impossible de créer l'agent après {self.max_retries + 1} tentatives. "
                f"Dernière erreur : {last_error}"
            )
        raise ToolExecutionError(
            f"Création échouée après {self.max_retries + 1} tentatives. "
            f"Dernière erreur : {last_error}"
        )

    # ── Autres outils ─────────────────────────────────────────────────────────

    async def _tool_list_agents(self) -> str:
        files = sorted(self.agents_dir.glob("*.py"))
        if not files:
            return "📂 Aucun agent créé pour l'instant."

        lines = ["📂 Agents disponibles :"]
        for f in files:
            try:
                first = f.read_text(encoding="utf-8").splitlines()[0].strip()
                desc  = first.lstrip('"""').lstrip("'''").strip() or "—"
            except Exception:
                desc = "informations indisponibles"
            lines.append(f"  • {f.stem} — {desc}")
        return "\n".join(lines)

    async def _tool_delete_agent(self, name: str) -> str:
        filepath = self.agents_dir / f"{name.lower()}.py"
        if not filepath.exists():
            raise ToolExecutionError(f"Agent '{name}' introuvable.")
        if not await self.submit_action({
            "action_type": "delete_agent",
            "preview": f"delete_agent: {name} ({filepath})",
            "reversible": False,
        }):
            return f"⛔ Suppression de '{name}' bloquée par ActionGate."
        try:
            filepath.unlink()
            self._stats["deleted"] += 1
            logger.info(f"🗑️ Agent '{name}' supprimé.")
        except OSError as exc:
            raise ToolExecutionError(f"Impossible de supprimer '{name}' : {exc}") from exc
        return f"✅ Agent '{name}' supprimé."

    # ── Entrée langage naturel ────────────────────────────────────────────────

    async def handle(self, query: str) -> str:
        q = query.lower()
        for trigger in ["crée un agent", "créer un agent", "génère un agent",
                        "fabrique un agent", "nouvel agent"]:
            if trigger in q:
                description = q.split(trigger, 1)[1].strip()
                if not description:
                    return "Décris l'agent que tu veux créer."
                return await self._tool_create_agent(description=description)
        return await super().handle(query)
