"""Moteur d'exécution — exécute les différents chemins d'action."""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.agents.planner_agent import PlannerAgent

from ...utils.errors import PathExecutionError, AgentNotFoundError
from ...utils.json_parser import JSONParseError, parse_json_safely
from ...utils.logger import logger


_THREAD_FUTURE_TIMEOUT: float = 2.0

# ── Classification de complexité ─────────────────────────────────────────────
_INSTANT_PATTERNS: set[str] = {
    "bonjour", "bonsoir", "salut", "hello", "hi", "hey", "coucou",
    "merci", "thanks", "ok", "oui", "non", "ouais", "nope",
    "ça va", "ca va", "comment vas-tu", "comment tu vas",
    "bye", "au revoir", "à plus", "bonne nuit", "bonne journée",
}

_COMPLEX_KEYWORDS: list[str] = [
    "analyse", "explique", "rédige", "écris un", "génère", "compare",
    "résume", "développe", "argumente", "détaille", "code", "debug",
    "script", "programme", "fonction", "algorithme", "en 5 points",
    "en détail", "étape par étape", "step by step",
]


def classify_query_complexity(query: str) -> str:
    """Classifie la complexité d'une requête.

    Returns:
        "instant" — salutations, oui/non (→ nano 0.5b, 50 tokens)
        "simple"  — questions courtes ≤ 10 mots (→ nano 0.5b, 100 tokens)
        "medium"  — questions moyennes ≤ 20 mots (→ speed 3b, 150 tokens)
        "complex" — analyse, rédaction (→ balanced 7b+, 256 tokens)
    """
    q = query.lower().strip().rstrip("!?.…")
    # Instant : salutations et réponses courtes
    if q in _INSTANT_PATTERNS or len(q.split()) <= 2:
        return "instant"
    # Complex : mots-clés de tâches longues
    if any(kw in q for kw in _COMPLEX_KEYWORDS):
        return "complex"
    # Simple : ≤ 10 mots, questions basiques → nano (rapide)
    if len(q.split()) <= 10:
        return "simple"
    # Medium : ≤ 20 mots → speed
    if len(q.split()) <= 20:
        return "medium"
    # > 20 mots → complex
    return "complex"


class ExecutionEngine:
    """Exécute les différents chemins d'action."""

    SIMPLE_ACTIONS: Dict[str, Tuple[str, str]] = {
        "ouvre": ("ComputerControlAgent", "open_application"),
        "open": ("ComputerControlAgent", "open_application"),
        "lance": ("ComputerControlAgent", "open_application"),
        "tape": ("ComputerControlAgent", "type_text"),
        "écris": ("ComputerControlAgent", "type_text"),
        "ecris": ("ComputerControlAgent", "type_text"),
        "type": ("ComputerControlAgent", "type_text"),
        "clique": ("ComputerControlAgent", "click"),
        "click": ("ComputerControlAgent", "click"),
        "capture": ("ComputerControlAgent", "get_screenshot"),
        "screenshot": ("ComputerControlAgent", "get_screenshot"),
        "capture d'écran": ("ComputerControlAgent", "get_screenshot"),
        "ferme": ("ComputerControlAgent", "close_window"),
        "close": ("ComputerControlAgent", "close_window"),
        "minimise": ("ComputerControlAgent", "minimize_window"),
        "minimize": ("ComputerControlAgent", "minimize_window"),
        "maximise": ("ComputerControlAgent", "maximize_window"),
        "maximize": ("ComputerControlAgent", "maximize_window"),
        "agrandis": ("ComputerControlAgent", "maximize_window"),
        "scrolle": ("ComputerControlAgent", "scroll"),
        "défile": ("ComputerControlAgent", "scroll"),
        "fais défiler": ("ComputerControlAgent", "scroll"),
        "organise": ("WorkspaceAgent", "smart_arrange"),
        "range les fenêtres": ("WorkspaceAgent", "smart_arrange"),
        "prépare mon espace": ("WorkspaceAgent", "smart_arrange"),
        "concentre-toi": ("WorkspaceAgent", "focus"),
        "côte à côte": ("WorkspaceAgent", "smart_arrange"),
        "côte-à-côte": ("WorkspaceAgent", "smart_arrange"),
        "side by side": ("WorkspaceAgent", "smart_arrange"),
        "partage l'écran": ("WorkspaceAgent", "smart_arrange"),
        "compare": ("WorkspaceAgent", "smart_arrange"),
        "disposition": ("WorkspaceAgent", "smart_arrange"),
        # Apple Ecosystem — Notes
        "crée une note": ("AppleEcosystemAgent", "create_note"),
        "nouvelle note": ("AppleEcosystemAgent", "create_note"),
        "ajoute une note": ("AppleEcosystemAgent", "create_note"),
        # Apple Ecosystem — Rappels
        "rappelle-moi": ("AppleEcosystemAgent", "create_reminder"),
        "rappelle moi": ("AppleEcosystemAgent", "create_reminder"),
        "crée un rappel": ("ReminderAgent", "create_reminder"),
        "créer un rappel": ("ReminderAgent", "create_reminder"),
        "rappel pour": ("ReminderAgent", "create_reminder"),
        # Calendrier — CalendarAgent
        "ajoute un événement": ("CalendarAgent", "add_event"),
        "ajouter un événement": ("CalendarAgent", "add_event"),
        "rendez-vous": ("CalendarAgent", "add_event"),
        "réunion": ("CalendarAgent", "add_event"),
        "événement": ("CalendarAgent", "add_event"),
        "planifie": ("CalendarAgent", "add_event"),
        # Documents — DocumentAgent
        "crée un document": ("DocumentAgent", "create_word_document"),
        "créer un document": ("DocumentAgent", "create_word_document"),
        "rédige un document": ("DocumentAgent", "create_word_document"),
        # Mail — SmartMailAgent pour traitement, AppleEcosystemAgent pour composition
        "traite mes mails": ("SmartMailAgent", "process_inbox"),
        "classe mes mails": ("SmartMailAgent", "process_inbox"),
        "lis mes mails": ("SmartMailAgent", "process_inbox"),
        "mes emails": ("SmartMailAgent", "process_inbox"),
        "surveille ma boîte mail": ("SmartMailAgent", "watch_inbox"),
        "réponds au mail": ("SmartMailAgent", "reply_mail"),
        "repond au mail": ("SmartMailAgent", "reply_mail"),
        "répond au mail": ("SmartMailAgent", "reply_mail"),
        "répondre au mail": ("SmartMailAgent", "reply_mail"),
        "réponds à ce mail": ("SmartMailAgent", "reply_mail"),
        "réponds au mail urgent": ("SmartMailAgent", "reply_mail"),
        "écris un mail": ("SmartMailAgent", "compose_mail"),
        "compose un mail": ("SmartMailAgent", "compose_mail"),
        "rédige un mail": ("SmartMailAgent", "compose_mail"),
        "confirme": ("SmartMailAgent", "confirm_mail"),
        "confirme le mail": ("SmartMailAgent", "confirm_mail"),
        "annule": ("SmartMailAgent", "confirm_mail"),
        "annule le mail": ("SmartMailAgent", "confirm_mail"),
        "envoie un mail": ("AppleEcosystemAgent", "compose_mail"),
        # Code — CodeDebugAgent
        "explique ce code": ("CodeDebugAgent", "explain_code"),
        "explique le code": ("CodeDebugAgent", "explain_code"),
        "trouve le bug": ("CodeDebugAgent", "find_bug"),
        "debug": ("CodeDebugAgent", "find_bug"),
        "refactore": ("CodeDebugAgent", "refactor_code"),
        "review le code": ("CodeDebugAgent", "review_code"),
        # Surveillance — WatchAgent
        "surveille": ("WatchAgent", "start_watch"),
        "monitore": ("WatchAgent", "start_watch"),
    }

    APP_ALIASES: Dict[str, str] = {
        "note": "Notes", "notes": "Notes",
        "calculatrice": "Calculator", "calculette": "Calculator",
        "safari": "Safari", "mail": "Mail",
        "calendrier": "Calendar", "rappels": "Reminders",
        "reminders": "Reminders", "calendar": "Calendar",
        "rappel": "Reminders",
        "terminal": "Terminal", "le terminal": "Terminal",
        "finder": "Finder", "le finder": "Finder",
        "chrome": "Google Chrome", "google chrome": "Google Chrome",
        "firefox": "Firefox",
        "slack": "Slack", "discord": "Discord", "spotify": "Spotify",
        "messages": "Messages", "musique": "Music", "music": "Music",
        "photos": "Photos", "contacts": "Contacts",
        "facetime": "FaceTime",
        "code": "Visual Studio Code", "vscode": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "pages": "Pages", "numbers": "Numbers", "keynote": "Keynote",
    }

    def __init__(
        self,
        registry: Any,
        planner: PlannerAgent,
        manager: Any,
        prompt_cache: Any,
        memory: Any,
        event_bus: Any,
        config: Dict[str, Any],
        loop: asyncio.AbstractEventLoop,
        model_mapping: Dict[str, str],
        llm_circuit_breaker: Optional[Any] = None,
        elasticity: Optional[Any] = None,
    ):
        self.registry = registry
        self.planner = planner
        self.manager = manager
        self.prompt_cache = prompt_cache
        self.memory = memory
        self.event_bus = event_bus
        self.config = config
        self.loop = loop
        self.model_mapping = model_mapping
        self.llm_circuit_breaker = llm_circuit_breaker
        self.elasticity = elasticity
        self.default_system = (
            "Tu es Lucie, une IA locale sur macOS. "
            "RÈGLES :\n"
            "1. Réponds en français, direct et concis.\n"
            "2. Pour une action simple → 1 phrase max ('Safari ouvert.', 'Note créée.').\n"
            "3. Pour une question → 2-3 phrases max, va droit au but.\n"
            "4. Pour une analyse/rédaction → développe autant que nécessaire.\n"
            "5. JAMAIS de préambule ('J'ai bien reçu...', 'Voici ma réponse...').\n"
            "6. JAMAIS d'excuse ou de refus vague — agis ou dis pourquoi en 1 phrase."
        )
        self.enable_memory = config.get("enable_memory", True)
        self.base_plan_timeout = config.get("plan_timeout", 30.0)
        # Contexte ContextWave courant (injecté par think())
        self._current_ctx: Optional[Any] = None
        # Prompt système nano pré-calculé (appelé des milliers de fois)
        self.nano_system = (
            "Tu es un assistant personnel local, amical et direct. "
            "Tu réponds en français, de façon concise (1-3 phrases max). "
            "Tu peux aider sur tous les sujets du quotidien."
        )

    def _run_coro_sync(self, coro: Any, timeout: float = _THREAD_FUTURE_TIMEOUT) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.error(f"Timeout dans _run_coro_sync après {timeout}s")
            raise
        except Exception as e:
            logger.error(f"Exception dans _run_coro_sync: {e}", exc_info=True)
            raise

    async def execute_direct_action(self, query: str) -> str:
        route = self._route_simple_action(query)
        if not route:
            # Fallback LLM classification si les keywords ne matchent pas
            intent = self._classify_intent_llm(query)
            if intent:
                action_type, confidence = intent
                agent_info = self._LLM_ACTION_TO_AGENT.get(action_type)
                if agent_info and agent_info[0]:
                    agent_name = agent_info[0]
                    agent = self.registry.get_agent(agent_name)
                    if hasattr(agent, "handle"):
                        logger.info(f"🧠 LLM → {agent_name}.handle() (conf={confidence:.2f})")
                        result = await agent.handle(query)
                        if result:
                            return result
            raise PathExecutionError("Aucune action directe trouvée")
        agent_name, action = route
        try:
            agent = self.registry.get_agent(agent_name)
            logger.debug(f"🔧 Exécution directe : {agent_name}.{action['tool']}")
            result = await agent.execute_tool(action["tool"], action["parameters"])
            if result.startswith("❌"):
                raise PathExecutionError(f"L'outil a retourné une erreur: {result}")
            return result
        except (AgentNotFoundError, PathExecutionError) as e:
            raise PathExecutionError(str(e)) from e
        except Exception as e:
            raise PathExecutionError(f"{agent_name}.{action['tool']} échoué: {e}") from e

    async def execute_multi_action(self, query: str) -> str:
        parts = re.split(r"\s+(et|puis)\s+", query, flags=re.IGNORECASE)
        results = []
        for part in parts:
            part = part.strip()
            if not part or part.lower() in ("et", "puis"):
                continue
            route = self._route_simple_action(part)
            if not route:
                raise PathExecutionError(f"Impossible de traiter la sous-action: {part}")
            agent_name, action = route
            agent = self.registry.get_agent(agent_name)
            try:
                result = await asyncio.wait_for(
                    agent.execute_tool(action["tool"], action["parameters"]),
                    timeout=15.0
                )
            except asyncio.TimeoutError:
                raise PathExecutionError(f"Timeout sur l'étape '{part}'")
            if result.startswith("❌"):
                raise PathExecutionError(f"Échec de la sous-action: {result}")
            results.append(result)
        if results:
            return "\n".join(results)
        raise PathExecutionError("Aucune action multiple trouvée")

    async def execute_visual_research(self, query: str) -> str:
        """Exécute le workflow de recherche visuelle Safari."""
        try:
            from app.agents.safari_research_workflow import SafariResearchWorkflow

            computer_agent = self.registry.get_agent("ComputerControlAgent")
            workflow = SafariResearchWorkflow(computer_agent, self.manager)
            result = await asyncio.wait_for(workflow.run(query), timeout=120.0)
            return result
        except AgentNotFoundError:
            raise PathExecutionError("ComputerControlAgent non disponible")
        except asyncio.TimeoutError:
            raise PathExecutionError("Recherche visuelle Safari timeout (120s)")
        except Exception as e:
            raise PathExecutionError(f"Recherche visuelle échouée: {e}") from e

    def execute_predicted_action(self, query: str) -> str:
        prediction = self._run_coro_sync(self._get_prediction(), timeout=1.0)
        if not prediction:
            raise PathExecutionError("Aucune prédiction disponible")
        agent_name = prediction.get("agent")
        tool_name = prediction.get("tool")
        params = prediction.get("parameters", {})
        if not agent_name or not tool_name:
            raise PathExecutionError("Prédiction incomplète")
        agent = self.registry.get_agent(agent_name)
        result = self._run_coro_sync(agent.execute_tool(tool_name, params))
        if result.startswith("❌"):
            raise PathExecutionError(f"Échec de l'action prédite: {result}")
        return result

    async def _get_prediction(self) -> Optional[Dict[str, Any]]:
        return None

    def execute_semantic_parsing(self, query: str) -> str:
        tools_desc = [
            f"- {name}.{tool.name}: {tool.description}"
            for name, agent in self.registry.agents.items()
            for tool in agent.get_tools()
        ]
        tools_str = "\n".join(tools_desc)
        prompt = (
            f"Tu es un assistant qui traduit des demandes en actions JSON.\n"
            f"Outils disponibles :\n{tools_str}\n\n"
            f'Demande : "{query}"\n\n'
            f"Génère une liste JSON d'actions. Réponds uniquement avec le JSON."
        )
        try:
            model_name = self.model_mapping.get("nano", "qwen2.5:0.5b")
            response = self.manager.generate(
                prompt=prompt, system="", model=model_name,
                temperature=0.1, max_tokens=512, timeout=3.0,
            )
            cleaned = response.strip()
            try:
                actions = parse_json_safely(cleaned, expected_type=list)
            except JSONParseError:
                match = re.search(r"(\[.*\])", cleaned, re.DOTALL)
                if not match:
                    raise PathExecutionError("Impossible de parser la réponse")
                actions = parse_json_safely(match.group(1), expected_type=list)

            if not actions:
                raise PathExecutionError("Aucune action générée")

            results = []
            for act in actions:
                agent_name = act.get("agent")
                tool_name = act.get("tool")
                params = act.get("parameters", {})
                agent = self.registry.get_agent(agent_name)
                result = self._run_coro_sync(agent.execute_tool(tool_name, params))
                if result.startswith("❌"):
                    raise PathExecutionError(f"Échec de l'action {tool_name}: {result}")
                results.append(result)
            return "\n".join(results)
        except Exception as exc:
            raise PathExecutionError(f"Échec parsing sémantique: {exc}") from exc

    def get_cached_response(self, query: str) -> str:
        systems = [self.nano_system, self.default_system]
        for system in systems:
            cached = self.prompt_cache.get(query, system=system, model="balanced")
            if cached:
                return cached
        raise PathExecutionError("Cache miss")

    def _get_nano_system(self) -> str:
        return (
            "Tu es un assistant personnel local, amical et direct. "
            "Tu réponds en français, de façon concise (1-3 phrases max). "
            "Tu peux aider sur tous les sujets du quotidien."
        )

    def call_llm(self, query: str, model_profile: str) -> str:
        enriched = self._enrich_query(query)

        # Choix adaptatif du modèle selon la complexité de la requête
        complexity = classify_query_complexity(query)

        if model_profile == "balanced":
            _COMPLEXITY_TO_PROFILE = {
                "instant": "nano",
                "simple":  "nano",
                "medium":  "speed",
                "complex": "balanced",
            }
            effective_profile = _COMPLEXITY_TO_PROFILE.get(complexity, "balanced")
        else:
            effective_profile = model_profile

        # Consulter ElasticityEngine — adapter le profil à la charge système
        if self.elasticity is not None:
            system_profile = self.elasticity.get_recommended_profile()
            _PROFILE_WEIGHT = {"speed": 0, "balanced": 1, "quality": 2}
            sys_weight = _PROFILE_WEIGHT.get(system_profile, 1)
            eff_weight = _PROFILE_WEIGHT.get(effective_profile, 1)
            # Si la charge système est élevée, forcer un profil plus léger
            if sys_weight < eff_weight:
                logger.info(
                    f"⚡ Profil système : {system_profile} "
                    f"(charge élevée → {effective_profile} réduit à {system_profile})"
                )
                effective_profile = system_profile

        model_name = self.model_mapping.get(effective_profile)

        # Tokens et timeout adaptés à la complexité
        _PROFILE_CONFIG: Dict[str, tuple] = {
            # (max_tokens, temperature, timeout)
            "nano":     (100, 0.3, 3.0),
            "speed":    (150, 0.3, 8.0),
            "balanced": (256, 0.5, 30.0),
            "quality":  (512, 0.5, 60.0),
        }
        tokens, temp, timeout = _PROFILE_CONFIG.get(
            effective_profile, (256, 0.5, 30.0)
        )

        if effective_profile == "nano":
            system = self.nano_system
        else:
            system = self.default_system

        logger.debug(
            f"LLM routing: complexity={complexity}, "
            f"profile={effective_profile}, model={model_name}, "
            f"tokens={tokens}, timeout={timeout}s"
        )

        def _generate(profile: str, model: Optional[str],
                      max_tokens: int, temperature: float,
                      max_timeout: float) -> str:
            sys_prompt = self.nano_system if profile == "nano" else system
            if model:
                return self.manager.generate(
                    prompt=enriched, system=sys_prompt,
                    model=model, temperature=temperature,
                    max_tokens=max_tokens, timeout=max_timeout,
                )
            else:
                return self.manager.generate(
                    prompt=enriched, system=sys_prompt,
                    timeout=max_timeout,
                )

        # Cascade de fallback : modèle choisi → speed → nano
        fallback_chain = []
        if effective_profile == "balanced":
            fallback_chain = [
                ("balanced", model_name, tokens, temp, timeout),
                ("speed", self.model_mapping.get("speed"), 150, 0.3, 8.0),
                ("nano", self.model_mapping.get("nano"), 50, 0.3, 3.0),
            ]
        elif effective_profile == "speed":
            fallback_chain = [
                ("speed", model_name, tokens, temp, timeout),
                ("nano", self.model_mapping.get("nano"), 50, 0.3, 3.0),
            ]
        else:
            fallback_chain = [
                (effective_profile, model_name, tokens, temp, timeout),
            ]

        response: Optional[str] = None
        last_error: Optional[Exception] = None

        for i, (prof, mod, tok, tmp, tout) in enumerate(fallback_chain):
            try:
                if i == 0 and self.llm_circuit_breaker is not None:
                    response = self.llm_circuit_breaker.call(
                        lambda p=prof, m=mod, t=tok, te=tmp, to=tout: _generate(p, m, t, te, to)
                    )
                else:
                    response = _generate(prof, mod, tok, tmp, tout)
                break
            except Exception as e:
                last_error = e
                logger.warning(f"LLM {mod} échoué ({e}), fallback suivant…")

        if response is None:
            raise PathExecutionError(
                f"Tous les modèles ont échoué: {last_error}"
            ) from last_error

        self.prompt_cache.put(query, system, "balanced", response)
        if self.enable_memory:
            self.memory.add_to_working(query, response)
            asyncio.run_coroutine_threadsafe(
                self.memory.add_episode(query, response, metadata={"latency": time.time()}),
                self.loop
            )
        return response

    async def generate_and_execute_plan(self, query: str) -> str:
        plan_dicts = self._get_cached_plan(query)
        if plan_dicts:
            from app.agents.planner_agent import PlanStep
            steps = [PlanStep(**step) for step in plan_dicts]
        else:
            steps = await self.planner.create_plan(query)
            if not steps:
                raise PathExecutionError("Impossible de générer un plan")
            plan_dicts = [step.dict() for step in steps]
            self._cache_plan(query, plan_dicts)

        timeout = self._get_dynamic_timeout(query, plan_needed=True)
        try:
            result = await asyncio.wait_for(
                self.planner.execute_plan(steps),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error("Timeout lors de l'exécution du plan")
            raise PathExecutionError("Le plan a pris trop de temps")
        return result

    async def execute_creation_agent(self, query: str) -> str:
        creator = self.registry.get_agent("CreatorAgent")
        q = query.lower()
        for prefix in ["crée un agent", "créer un agent", "génère un agent", "fabrique un agent"]:
            if prefix in q:
                description = q.split(prefix, 1)[1].strip()
                if description:
                    result = await creator.execute_tool("create_agent", {"description": description})
                    return result
        return await creator.execute_tool("create_agent", {"description": query})

    # ── Classification LLM — intention avant keywords ──────────────────────
    _LLM_ACTION_TO_AGENT: Dict[str, Tuple[str, str]] = {
        "reminder": ("AppleEcosystemAgent", "create_reminder"),
        "calendar": ("CalendarAgent", "add_event"),
        "file": ("FileAgent", ""),
        "note": ("AppleEcosystemAgent", "create_note"),
        "mail": ("AppleEcosystemAgent", "read_mail"),
        "code": ("CodeDebugAgent", "explain_code"),
        "search": ("", ""),  # → pipeline visual_research
        "document": ("DocumentAgent", "create_word_document"),
        "open_app": ("ComputerControlAgent", "open_application"),
    }

    def _classify_intent_llm(self, query: str) -> Optional[Tuple[str, float]]:
        """Classifie l'intention via qwen2.5:0.5b. Retourne (action, confidence) ou None."""
        try:
            model_name = self.model_mapping.get("nano", "qwen2.5:0.5b")
            system = (
                "Tu es un classificateur d'intention. "
                "Réponds UNIQUEMENT avec un JSON : "
                '{"action": "reminder|calendar|file|note|mail|code|search|document|open_app|question", '
                '"confidence": 0.0-1.0} '
                "Rien d'autre. Pas d'explication."
            )
            response = self.manager.generate(
                prompt=query, system=system, model=model_name,
                temperature=0.1, max_tokens=60, timeout=3.0,
            )
            # Parser le JSON
            import json as _json
            cleaned = response.strip()
            # Extraire le JSON de la réponse
            match = re.search(r'\{[^}]+\}', cleaned)
            if not match:
                return None
            data = _json.loads(match.group())
            action = data.get("action", "question")
            confidence = float(data.get("confidence", 0.0))
            if action and action != "question" and confidence > 0.7:
                logger.info(f"🧠 LLM classification: {action} ({confidence:.2f})")
                return action, confidence
        except Exception as e:
            logger.debug(f"LLM classification échouée (non bloquant): {e}")
        return None

    def _route_simple_action(self, query: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        q = query.lower()
        for keyword, (agent_name, tool_name) in self.SIMPLE_ACTIONS.items():
            if keyword not in q:
                continue
            if tool_name == "open_application":
                rest = q.replace(keyword, "").strip()
                match = re.search(r"^(.*?)(?:\s+(?:et|puis)\s+|$)", rest)
                if match:
                    rest = match.group(1).strip()
                if not rest:
                    continue
                rest = re.sub(r'^["\'](.*)["\']$', r"\1", rest)
                normalized = self.APP_ALIASES.get(rest.lower())
                if normalized:
                    rest = normalized
                return agent_name, {"tool": tool_name, "parameters": {"app_name": rest}}
            elif tool_name == "type_text":
                pattern = r"\b" + re.escape(keyword) + r'\s*"([^"]+)"'
                m = re.search(pattern, query, re.IGNORECASE)
                text = m.group(1) if m else query.replace(keyword, "", 1).strip()
                if text.lower().startswith(("et", "puis")):
                    return None
                app_m = re.search(r"(?:dans|sur)\s+([a-zA-Z]+)", q, re.IGNORECASE)
                params: Dict[str, Any] = {"text": text}
                if app_m:
                    params["app_name"] = app_m.group(1)
                return agent_name, {"tool": tool_name, "parameters": params}
            elif tool_name == "click":
                m = re.search(r"(\d+)[,\s]+(\d+)", query)
                if m:
                    return agent_name, {
                        "tool": tool_name,
                        "parameters": {"x": int(m.group(1)), "y": int(m.group(2))},
                    }
            elif tool_name == "get_screenshot":
                return agent_name, {"tool": tool_name, "parameters": {}}
            elif tool_name == "smart_arrange":
                return agent_name, {"tool": tool_name, "parameters": {"task_description": query}}
            elif tool_name == "focus":
                focus_match = re.search(r"(?:sur|à|on)\s+([a-zA-Z\s]+)", q, re.IGNORECASE)
                focus_params: Dict[str, Any] = {}
                if focus_match:
                    app = focus_match.group(1).strip()
                    normalized = self.APP_ALIASES.get(app.lower())
                    focus_params["app_name"] = normalized if normalized else app.capitalize()
                return agent_name, {"tool": tool_name, "parameters": focus_params}
            elif tool_name == "scroll":
                direction = "up" if any(w in q for w in ["haut", "up", "monte"]) else "down"
                amount_match = re.search(r"(\d+)", query)
                amount = int(amount_match.group(1)) if amount_match else 3
                return agent_name, {"tool": tool_name, "parameters": {"direction": direction, "amount": amount}}
            elif tool_name in ("close_window", "minimize_window", "maximize_window"):
                rest = q.replace(keyword, "").strip()
                rest = re.sub(r"^(l'|le |la |les )", "", rest, flags=re.IGNORECASE).strip() if rest else ""
                ignore_words = {"fenêtre", "fenetre", "window", "app", "application", "tout", "toutes"}
                win_params: Dict[str, Any] = {}
                if rest and rest.lower() not in ignore_words:
                    normalized = self.APP_ALIASES.get(rest.lower())
                    win_params["app_name"] = normalized if normalized else rest
                return agent_name, {"tool": tool_name, "parameters": win_params}
            elif tool_name == "create_note":
                # Extraire le contenu après "crée une note"
                content = q
                for prefix in ["crée une note qui dit ", "crée une note "]:
                    if prefix in q:
                        content = query[q.index(prefix) + len(prefix):]
                        break
                return agent_name, {"tool": tool_name, "parameters": {"content": content}}
            elif tool_name == "create_reminder":
                import re as _re
                from datetime import datetime as _dt, timedelta as _td
                rest = q.replace(keyword, "").strip()
                params_r: Dict[str, Any] = {}
                # Extraction "dans X minutes"
                minutes_match = _re.search(r"dans\s+(\d+)\s+minutes?\s*", rest)
                if minutes_match:
                    params_r["minutes"] = int(minutes_match.group(1))
                    rest = rest[:minutes_match.start()] + rest[minutes_match.end():]
                # Extraction heure "à 9h", "à 18h30", "à 14:00"
                h_match = _re.search(r"(?:à|a)\s+(\d{1,2})\s*[h:]?\s*(\d{2})?", rest)
                if h_match:
                    hour = int(h_match.group(1))
                    minute = int(h_match.group(2) or 0)
                    # Calcul date cible
                    now = _dt.now()
                    if "demain" in rest:
                        target = now + _td(days=1)
                    elif "après-demain" in rest or "après demain" in rest:
                        target = now + _td(days=2)
                    else:
                        target = now
                        # Si l'heure est déjà passée aujourd'hui → demain
                        if hour < now.hour or (hour == now.hour and minute <= now.minute):
                            target = now + _td(days=1)
                    target = target.replace(hour=hour, minute=minute, second=0)
                    params_r["due_date"] = target.strftime("%Y-%m-%d %H:%M")
                    # Retirer la partie heure du texte pour le titre
                    rest = _re.sub(r"(?:à|a)\s+\d{1,2}\s*[h:]?\s*\d{0,2}", "", rest).strip()
                elif "demain" in rest and "minutes" not in str(params_r):
                    # "demain" sans heure → rappel demain matin 9h
                    target = _dt.now() + _td(days=1)
                    target = target.replace(hour=9, minute=0, second=0)
                    params_r["due_date"] = target.strftime("%Y-%m-%d %H:%M")
                # Nettoyage du titre
                rest = _re.sub(r"\b(demain|après[- ]demain|aujourd'hui)\b", "", rest, flags=_re.IGNORECASE).strip()
                rest = _re.sub(r"^(de|d'|que|pour)\s+", "", rest.strip()).strip()
                # ReminderAgent attend "title", AppleEcosystemAgent attend "task"
                param_key = "title" if agent_name == "ReminderAgent" else "task"
                params_r[param_key] = rest if rest else query
                return agent_name, {"tool": tool_name, "parameters": params_r}
            elif tool_name == "add_event":
                # Calendrier — extraire titre, date et heure
                import re as _re
                from datetime import datetime as _dt, timedelta as _td
                rest = q.replace(keyword, "").strip()
                # Extraction de la date relative
                now = _dt.now()
                if "demain" in rest:
                    target = now + _td(days=1)
                elif "après-demain" in rest or "après demain" in rest:
                    target = now + _td(days=2)
                else:
                    target = now
                # Extraction de l'heure
                h_match = _re.search(r"(?:à|a)\s+(\d{1,2})\s*[h:]?\s*(\d{2})?", rest)
                if h_match:
                    hour = int(h_match.group(1))
                    minute = int(h_match.group(2)) if h_match.group(2) else 0
                    target = target.replace(hour=hour, minute=minute)
                date_str = target.strftime("%Y-%m-%d %H:%M")
                # Extraire le titre (retirer les mots de date/heure)
                title = _re.sub(r"\b(demain|après[- ]demain|aujourd'hui|à\s+\d{1,2}\s*[h:]\s*\d{0,2})\b", "", rest, flags=_re.IGNORECASE).strip()
                title = _re.sub(r"^(ajoute\s+un\s*|un\s+)", "", title, flags=_re.IGNORECASE).strip()
                if not title:
                    title = rest or query
                return agent_name, {"tool": tool_name, "parameters": {"title": title, "date": date_str}}
            elif tool_name in ("explain_code", "find_bug", "refactor_code", "review_code"):
                # Code — passer la requête comme code ou description
                rest = q.replace(keyword, "").strip()
                params_code: Dict[str, Any] = {"code": rest or query}
                if tool_name == "find_bug":
                    params_code = {"code": rest or query, "error": ""}
                elif tool_name == "refactor_code":
                    params_code = {"code": rest or query, "instructions": ""}
                return agent_name, {"tool": tool_name, "parameters": params_code}
            elif tool_name == "create_word_document":
                rest = q
                for prefix in ["crée un document sur ", "créer un document sur ",
                                "rédige un document sur ", "crée un document ", "créer un document "]:
                    if prefix in q:
                        rest = query[q.index(prefix) + len(prefix):]
                        break
                topic = rest.strip() or query
                # Le contrat attend title et content — titre = sujet, contenu placeholder
                return agent_name, {"tool": tool_name, "parameters": {"title": topic, "content": topic}}
            elif tool_name == "process_inbox":
                return agent_name, {"tool": tool_name, "parameters": {"limit": 5}}
            elif tool_name == "watch_inbox":
                return agent_name, {"tool": tool_name, "parameters": {"interval": 300}}
            elif tool_name == "reply_mail":
                return agent_name, {"tool": tool_name, "parameters": {"subject": "", "sender": "", "content": ""}}
            elif tool_name == "compose_mail" and agent_name == "SmartMailAgent":
                return agent_name, {"tool": tool_name, "parameters": {"to": "", "subject": "", "content": ""}}
            elif tool_name == "confirm_mail":
                action = "cancel" if "annule" in q else "confirm"
                return agent_name, {"tool": tool_name, "parameters": {"action": action}}
            elif tool_name == "read_mail":
                return agent_name, {"tool": tool_name, "parameters": {}}
            elif tool_name == "compose_mail":
                rest = q.replace(keyword, "").strip()
                return agent_name, {"tool": tool_name, "parameters": {"to": rest, "subject": "", "body": ""}}
            elif tool_name == "start_watch":
                # Extraire le sujet et la condition
                import re as _re
                rest = q.replace(keyword, "").strip()
                # Pattern : "X et préviens-moi si Y"
                match = _re.search(
                    r"(.+?)\s+(?:et\s+)?(?:préviens|alerte|notifie)[- ]moi\s+(?:si|quand)\s+(.+)",
                    rest, _re.IGNORECASE
                )
                if match:
                    topic = match.group(1).strip()
                    condition = match.group(2).strip()
                else:
                    topic = rest
                    condition = "changement significatif"
                return agent_name, {"tool": tool_name, "parameters": {
                    "topic": topic, "condition": condition, "check_interval": 300
                }}
        return None

    def _get_dynamic_timeout(self, query: str, plan_needed: bool) -> float:
        base = self.base_plan_timeout if plan_needed else 5.0
        estimated = base * (1 + len(query.split()) / 100)
        return min(estimated, self.base_plan_timeout * 2)

    def _enrich_query(self, query: str) -> str:
        if self.enable_memory:
            ctx = self.memory.get_working_context(n=3)
            if ctx:
                return f"Contexte récent:\n{ctx}\n\n{query}"
        return query

    def _get_cached_plan(self, query: str) -> Optional[List[Dict[str, Any]]]:
        try:
            return self.prompt_cache.get_plan(query, similarity_threshold=0.75)
        except Exception as exc:
            logger.error(f"Erreur récupération plan cache: {exc}")
            return None

    def _cache_plan(self, query: str, plan: List[Dict[str, Any]]) -> None:
        try:
            self.prompt_cache.put_plan(query, plan)
        except Exception as exc:
            logger.error(f"Erreur stockage plan cache: {exc}")

    # ── LLM Résonance — vibration progressive ────────────────────────────

    async def _call_with_timeout(
        self, profile: str, prompt: str, timeout: float,
    ) -> Optional[str]:
        """Appel LLM avec timeout dans un executor."""
        model_name = self.model_mapping.get(profile)
        if not model_name:
            return None

        _PROFILE_CONFIG: Dict[str, tuple] = {
            "nano":     (100, 0.3),
            "speed":    (150, 0.3),
            "balanced": (256, 0.5),
            "quality":  (512, 0.5),
        }
        tokens, temp = _PROFILE_CONFIG.get(profile, (256, 0.5))

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.manager.generate(
                        prompt=prompt,
                        system=self.default_system if profile != "nano" else self.nano_system,
                        model=model_name,
                        temperature=temp,
                        max_tokens=tokens,
                        timeout=timeout,
                    ),
                ),
                timeout=timeout,
            )
            if result and result.strip():
                logger.info(f"🔔 Résonance {profile} → réponse en {timeout:.1f}s max")
                return result
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Résonance {profile} silencieuse: {e}")
        return None

    async def llm_resonance(self, ctx: Any, prompt: str) -> str:
        """
        Vibration progressive — Loi de Résonance.
        nano vibre immédiatement, speed entre à 2s, balanced à 4s.
        Premier résultat annule les autres.
        Budget global respecté via ctx.remaining().
        """
        tasks: Dict[str, asyncio.Task] = {}

        # nano entre en vibration immédiatement
        tasks["nano"] = asyncio.create_task(
            self._call_with_timeout("nano", prompt, ctx.get_effective_timeout(3.0))
        )

        # Attendre 2s — nano répond souvent ici
        done, _ = await asyncio.wait(
            list(tasks.values()),
            timeout=min(2.0, ctx.remaining()),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if done:
            result = list(done)[0].result()
            if result:
                for t in tasks.values():
                    if not t.done():
                        t.cancel()
                return result

        # speed entre en vibration
        if not ctx.is_expired():
            tasks["speed"] = asyncio.create_task(
                self._call_with_timeout("speed", prompt, ctx.get_effective_timeout(8.0))
            )

        done, _ = await asyncio.wait(
            list(tasks.values()),
            timeout=min(3.0, ctx.remaining()),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if done:
            result = list(done)[0].result()
            if result:
                for t in tasks.values():
                    if not t.done():
                        t.cancel()
                return result

        # balanced entre en vibration
        if not ctx.is_expired():
            tasks["balanced"] = asyncio.create_task(
                self._call_with_timeout("balanced", prompt, ctx.get_effective_timeout(15.0))
            )

        # Attendre le premier résultat
        done, pending = await asyncio.wait(
            list(tasks.values()),
            timeout=ctx.remaining(),
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Annuler les vibrations restantes
        for p in pending:
            p.cancel()

        if done:
            result = list(done)[0].result()
            if result:
                return result

        from ...utils.errors import PathExecutionError
        raise PathExecutionError(
            f"Budget onde épuisé ({ctx.budget}s) — aucun LLM n'a répondu"
        )
