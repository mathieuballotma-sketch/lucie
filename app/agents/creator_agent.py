"""
Creator Agent — Génère de nouveaux agents à partir d'une description.
Corrections appliquées :
  - Filtre AST étendu (accès dangereux via __subclasses__, __globals__, etc.)
  - Fix __builtins__ (module ou dict selon le contexte)
  - Récursion remplacée par une boucle (plus de risque de stack overflow)
  - Test async réellement exécuté
  - Liste d'outils dynamique
  - _notify_user branché sur l'event bus

Principes :
  • Homéostasie  : validation + tests du code généré
  • Évolution    : apprentissage par les échecs, métriques
  • Symbiose     : notifications via event bus
  • Moindre action : retries intelligents, prompts ciblés
"""

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import ast
import concurrent.futures

from pydantic import BaseModel, Field, validator

from app.agents.base_agent import BaseAgent, Tool
from app.providers.manager import ProviderManager
from app.brain.synapses.event_bus import EventBus
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.metrics import MetricsCollector


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────
class AgentCreationError(Exception):
    """Erreur lors de la création d'un agent."""


class InvalidAgentCodeError(AgentCreationError):
    """Le code généré est invalide ou dangereux."""


class AgentTestError(AgentCreationError):
    """Le code généré a échoué aux tests."""


# ─────────────────────────────────────────────────────────────────────────────
# Contrats Pydantic
# ─────────────────────────────────────────────────────────────────────────────
class CreateAgentContract(BaseModel):
    description: str = Field(
        ..., description="Description de l'agent à créer", min_length=5
    )
    name: Optional[str] = Field(None, description="Nom souhaité (optionnel)")

    @validator("name")
    def validate_name(cls, v):
        if v is not None and not re.match(r"^[A-Z][a-zA-Z0-9_]*$", v):
            raise ValueError(
                "Le nom doit commencer par une majuscule et ne contenir "
                "que des lettres, chiffres et underscores"
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
    1. Sécurité — imports interdits + accès aux attributs dangereux
    2. Fonctionnel — instanciation, get_tools(), handle()
    """

    # Modules dont l'import est interdit
    FORBIDDEN_IMPORTS: Set[str] = {
        "os", "subprocess", "socket", "requests", "urllib",
        "shutil", "tempfile", "ctypes", "importlib",
    }

    # Noms interdits dans les builtins et les appels
    FORBIDDEN_BUILTINS: Set[str] = {
        "eval", "exec", "compile", "__import__", "open",
        "breakpoint", "input",
    }

    # Attributs dangereux qui permettent d'échapper au sandbox
    # (ex: ().__class__.__bases__[0].__subclasses__() → accès à os via sys)
    FORBIDDEN_ATTRS: Set[str] = {
        "__subclasses__", "__globals__", "__builtins__",
        "__class__", "__bases__", "__mro__", "__init_subclass__",
        "__reduce__", "__reduce_ex__",
    }

    def __init__(
        self,
        allowed_tools: Optional[List[str]] = None,
        llm_service=None,
    ):
        self.allowed_tools = allowed_tools or []
        self.llm_service = llm_service

    # ── Sécurité ─────────────────────────────────────────────────────────────
    def validate_safety(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Analyse statique du code via AST.
        Retourne (True, class_name) ou (False, message_erreur).
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Erreur de syntaxe : {e}"

        for node in ast.walk(tree):

            # ── Imports interdits ──────────────────────────────────────────
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

            # ── Appels à des builtins dangereux ────────────────────────────
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.FORBIDDEN_BUILTINS:
                        return False, f"Appel interdit : {node.func.id}()"

            # ── Accès aux attributs dangereux (bypass sandbox) ─────────────
            elif isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN_ATTRS:
                    return False, (
                        f"Accès à un attribut interdit : {node.attr} "
                        f"(tentative de contournement du sandbox)"
                    )

        # ── Présence d'une classe héritant de BaseAgent ────────────────────
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

    # ── Tests fonctionnels ────────────────────────────────────────────────────
    async def test_functionality(
        self,
        code: str,
        class_name: str,
        loop: asyncio.AbstractEventLoop,
    ) -> Tuple[bool, Optional[str]]:
        """
        Exécute le code dans un namespace restreint (thread isolé) puis
        teste instanciation, get_tools() et handle().
        """
        # ── Namespace restreint ───────────────────────────────────────────
        # FIX : __builtins__ peut être un module ou un dict selon le contexte
        raw_builtins = __builtins__
        if isinstance(raw_builtins, dict):
            safe_builtins = {
                k: v for k, v in raw_builtins.items()
                if k not in self.FORBIDDEN_BUILTINS
            }
        else:
            import builtins as _builtins_module
            safe_builtins = {
                k: v for k, v in vars(_builtins_module).items()
                if k not in self.FORBIDDEN_BUILTINS
            }

        namespace: Dict[str, Any] = {
            "__builtins__": safe_builtins,
            "BaseAgent": BaseAgent,
            "Tool": Tool,
            "Optional": Optional,
            "List": List,
            "Dict": Dict,
            "Any": Any,
        }

        # ── Exécution dans un thread (évite de bloquer la boucle événements) ─
        def _run_code() -> Optional[str]:
            try:
                exec(code, namespace)  # noqa: S102
                return None
            except Exception as exc:
                return str(exc)

        try:
            exec_error = await loop.run_in_executor(None, _run_code)
        except concurrent.futures.TimeoutError:
            return False, "Timeout lors de l'exécution (boucle infinie ?)"
        except Exception as exc:
            return False, f"Exception inattendue : {exc}"

        if exec_error:
            return False, f"Erreur d'exécution : {exec_error}"

        # ── Récupération de la classe ─────────────────────────────────────
        agent_class = namespace.get(class_name)
        if not agent_class:
            return False, f"Classe {class_name} introuvable après exécution"

        if not issubclass(agent_class, BaseAgent):
            return False, f"{class_name} n'hérite pas de BaseAgent"

        # ── Instanciation ─────────────────────────────────────────────────
        try:
            agent = agent_class(llm_service=None, bus=None, config={})
        except Exception as exc:
            return False, f"Erreur lors de l'instanciation : {exc}"

        # ── get_tools() ───────────────────────────────────────────────────
        try:
            tools = agent.get_tools()
            if not isinstance(tools, list):
                return False, "get_tools() ne retourne pas une liste"
            for tool in tools:
                if not isinstance(tool, Tool):
                    return False, f"Outil invalide : {tool!r}"
                if self.allowed_tools and tool.name not in self.allowed_tools:
                    return False, (
                        f"Outil '{tool.name}' non autorisé "
                        f"(autorisés : {self.allowed_tools})"
                    )
        except Exception as exc:
            return False, f"Erreur dans get_tools() : {exc}"

        # ── handle() — exécuté réellement si async ────────────────────────
        try:
            result = agent.handle("test query")
            if asyncio.iscoroutine(result):
                result = await result          # FIX : on exécute vraiment la coroutine
            if not isinstance(result, str):
                return False, (
                    f"handle() a retourné {type(result).__name__} au lieu de str"
                )
        except Exception as exc:
            return False, f"Erreur dans handle() : {exc}"

        return True, None


# ─────────────────────────────────────────────────────────────────────────────
# CreatorAgent
# ─────────────────────────────────────────────────────────────────────────────
class CreatorAgent(BaseAgent):
    """
    Génère, valide et enregistre de nouveaux agents à la volée.
    La création passe par un pipeline :
      génération LLM → validation AST → tests fonctionnels → sauvegarde → événement
    En cas d'échec, le pipeline retente en injectant l'erreur dans le prompt.
    """

    def __init__(
        self,
        llm_service: ProviderManager,
        bus: Any,
        event_bus: EventBus,
        config: dict,
        agents_dir: Path,
        available_tools: Optional[List[str]] = None,
    ):
        super().__init__("CreatorAgent", llm_service, bus)
        self.event_bus  = event_bus
        self.agents_dir = agents_dir
        self.agents_dir.mkdir(parents=True, exist_ok=True)

        # Config
        self.model_profile       = config.get("creator_model",          "balanced")
        self.fallback_model      = config.get("creator_fallback_model",  "speed")
        self.generation_timeout  = config.get("creator_timeout",         30.0)
        self.max_retries         = config.get("creator_max_retries",     3)
        self.ask_user_on_failure = config.get("ask_user_on_failure",     True)

        # Circuit breaker
        self.circuit_breaker = (
            CircuitBreaker(
                name="creator_llm",
                failure_threshold=3,
                recovery_timeout=60,
            )
            if config.get("enable_circuit_breaker", True)
            else None
        )

        # Métriques
        self.metrics = MetricsCollector()

        # Outils disponibles (fournis dynamiquement par le cortex)
        if available_tools is None:
            logger.warning(
                "CreatorAgent : aucune liste d'outils fournie — "
                "les agents générés ne pourront utiliser que les outils par défaut."
            )
            self._available_tools: List[str] = []
        else:
            self._available_tools = available_tools

        self.validator = AgentCodeValidator(
            allowed_tools=self._available_tools,
            llm_service=llm_service,
        )

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

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _extract_class_name(self, code: str) -> Optional[str]:
        """Extrait le nom de la première classe héritant de BaseAgent."""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "BaseAgent":
                            return node.name
        except SyntaxError:
            pass
        return None

    async def _generate_agent_code(
        self,
        description: str,
        name: Optional[str],
        attempt: int,
        previous_error: Optional[str],
    ) -> Optional[str]:
        """Génère le code Python de l'agent via le LLM."""
        tools_str = (
            ", ".join(self._available_tools)
            if self._available_tools
            else "aucun outil connu"
        )

        prompt = f"""Tu es un générateur de code pour des agents IA.
L'utilisateur veut créer un agent capable de :
{description}

Génère une classe Python complète héritant de `BaseAgent` avec :
- `get_tools()` → liste d'outils parmi : {tools_str}
- `handle(self, query: str) -> str` → logique de l'agent
- Des méthodes `_tool_*` si nécessaire

Règles :
- Nom de classe : {"utilise " + name if name else "invente un nom pertinent (ex: WeatherAgent)"}
- Docstrings obligatoires
- Imports depuis app.agents.base_agent uniquement
- Réponds UNIQUEMENT avec le code Python, sans texte autour
"""
        if previous_error:
            prompt += (
                f"\n\nLa tentative précédente a échoué : {previous_error}\n"
                "Corrige précisément cette erreur."
            )

        model = self.model_profile if attempt == 0 else self.fallback_model

        async def _call() -> str:
            loop = asyncio.get_running_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.llm.generate(
                        prompt=prompt,
                        system="",
                        model=model,
                        temperature=0.2,
                        max_tokens=1500,
                        timeout=self.generation_timeout,
                    ),
                ),
                timeout=self.generation_timeout + 2.0,
            )

        try:
            response = (
                await self.circuit_breaker.call_async(_call)
                if self.circuit_breaker
                else await _call()
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout LLM (tentative {attempt + 1})")
            self.metrics.increment("creator.llm_timeout")
            return None
        except Exception as exc:
            logger.error(f"Erreur LLM : {exc}")
            self.metrics.increment("creator.llm_error")
            return None

        # Nettoyer les éventuels blocs markdown
        code = response.strip()
        for fence in ("```python", "```"):
            if code.startswith(fence):
                code = code[len(fence):]
        if code.endswith("```"):
            code = code[:-3]
        return code.strip()

    async def _notify_user(
        self, message: str, code: Optional[str] = None
    ) -> bool:
        """Publie une notification sur l'event bus (HUD la recevra)."""
        logger.warning(f"👤 Notification : {message}")
        await self.event_bus.publish(
            "user.notification",
            {
                "level":   "warning",
                "message": message,
                "code":    code,
                "source":  self.name,
            },
        )
        return False

    # ── Pipeline de création (boucle, plus de récursion) ─────────────────────
    async def _tool_create_agent(
        self,
        description: str,
        name: Optional[str] = None,
    ) -> str:
        """
        Pipeline complet : génération → validation → test → sauvegarde.
        FIX : boucle for au lieu de récursion (évite stack overflow).
        """
        last_error: Optional[str] = None

        for attempt in range(self.max_retries + 1):
            self.metrics.increment("creator.create_attempts")
            logger.info(f"🧙 Tentative {attempt + 1}/{self.max_retries + 1} — {description}")

            # 1 ── Génération du code ──────────────────────────────────────
            code = await self._generate_agent_code(
                description, name, attempt, last_error
            )
            if not code:
                last_error = "Échec de génération du code"
                continue

            # 2 ── Validation de sécurité ──────────────────────────────────
            safe, result = self.validator.validate_safety(code)
            if not safe:
                last_error = f"Sécurité : {result}"
                logger.warning(last_error)
                self.metrics.increment("creator.safety_failures")
                continue

            class_name: str = result  # type: ignore[assignment]

            # 3 ── Vérification de l'unicité du nom ───────────────────────
            filepath = self.agents_dir / f"{class_name.lower()}.py"
            if filepath.exists():
                last_error = f"Un agent '{class_name}' existe déjà"
                logger.warning(last_error)
                # Suffixer le nom pour la prochaine tentative
                name = f"{class_name}_{attempt + 2}"
                continue

            # 4 ── Tests fonctionnels ──────────────────────────────────────
            loop = asyncio.get_running_loop()
            ok, test_error = await self.validator.test_functionality(
                code, class_name, loop
            )
            if not ok:
                last_error = f"Tests : {test_error}"
                logger.warning(last_error)
                self.metrics.increment("creator.test_failures")
                continue

            # 5 ── Sauvegarde ──────────────────────────────────────────────
            try:
                filepath.write_text(code, encoding="utf-8")
                logger.info(f"✅ Agent '{class_name}' sauvegardé → {filepath}")
                self.metrics.increment("creator.create_success")
            except IOError as exc:
                raise ToolExecutionError(
                    f"Impossible d'écrire {filepath} : {exc}"
                ) from exc

            # 6 ── Événement ───────────────────────────────────────────────
            await self.event_bus.publish(
                "agent.created",
                {"name": class_name, "path": str(filepath)},
                self.name,
            )

            return f"✅ Agent '{class_name}' créé avec succès."

        # Toutes les tentatives ont échoué
        if self.ask_user_on_failure:
            await self._notify_user(
                f"Impossible de créer l'agent après {self.max_retries + 1} "
                f"tentatives. Dernière erreur : {last_error}"
            )
        raise ToolExecutionError(
            f"Création échouée après {self.max_retries + 1} tentatives. "
            f"Dernière erreur : {last_error}"
        )

    # ── Autres outils ─────────────────────────────────────────────────────────
    async def _tool_list_agents(self) -> str:
        """Liste les agents créés avec leur description."""
        files = sorted(self.agents_dir.glob("*.py"))
        if not files:
            return "📂 Aucun agent créé pour l'instant."

        lines = ["📂 Agents disponibles :"]
        for f in files:
            try:
                first = f.read_text(encoding="utf-8").splitlines()[0].strip()
                # Extraire la docstring si possible
                desc = first.lstrip('"""').lstrip("'''").strip() or "—"
            except Exception:
                desc = "informations indisponibles"
            lines.append(f"  • {f.stem} — {desc}")
        return "\n".join(lines)

    async def _tool_delete_agent(self, name: str) -> str:
        """Supprime un agent créé."""
        filepath = self.agents_dir / f"{name.lower()}.py"
        if not filepath.exists():
            raise ToolExecutionError(f"Agent '{name}' introuvable.")
        try:
            filepath.unlink()
            self.metrics.increment("creator.delete_success")
            logger.info(f"🗑️ Agent '{name}' supprimé.")
        except OSError as exc:
            raise ToolExecutionError(
                f"Impossible de supprimer '{name}' : {exc}"
            ) from exc
        return f"✅ Agent '{name}' supprimé."

    # ── Entrée langage naturel ────────────────────────────────────────────────
    async def handle(self, query: str) -> str:
        """Crée un agent via une phrase en langage naturel."""
        q = query.lower()
        triggers = [
            "crée un agent", "créer un agent",
            "génère un agent", "fabrique un agent",
            "nouvel agent",
        ]
        for trigger in triggers:
            if trigger in q:
                description = q.split(trigger, 1)[1].strip()
                if not description:
                    return "Décris l'agent que tu veux créer."
                return await self._tool_create_agent(description=description)
        return await super().handle(query)