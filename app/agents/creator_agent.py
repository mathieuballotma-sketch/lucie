"""
Creator Agent - Agent capable de générer de nouveaux agents à partir d'une description.
Incarne les principes d'évolution (création de nouveaux agents) et de symbiose (intégration dans l'écosystème).
"""

import asyncio
import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError

# -----------------------------------------------------------------------
# Contrats Pydantic pour les outils
# -----------------------------------------------------------------------
class CreateAgentContract(BaseModel):
    description: str = Field(..., description="Description en langage naturel de l'agent à créer")
    name: Optional[str] = Field(None, description="Nom souhaité pour l'agent (optionnel)")

class ListAgentsContract(BaseModel):
    pass

class DeleteAgentContract(BaseModel):
    name: str = Field(..., description="Nom de l'agent à supprimer")

# -----------------------------------------------------------------------
# Agent créateur
# -----------------------------------------------------------------------
class CreatorAgent(BaseAgent):
    """
    Agent capable de générer de nouveaux agents à partir d'une description textuelle.
    Utilise le LLM pour produire le code de la classe de l'agent, puis l'enregistre dans le système.
    """

    def __init__(self, llm_service, bus, event_bus, config: dict, agents_dir: Path):
        super().__init__("CreatorAgent", llm_service, bus)
        self.event_bus = event_bus
        self.agents_dir = agents_dir
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self._tools_cache = None
        logger.info(f"🧙 CreatorAgent initialisé, répertoire des agents : {self.agents_dir}")

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
        # Ce n'est pas un agent de traitement direct, il répond via ses outils
        return False

    async def handle(self, query: str) -> str:
        """
        Méthode principale pour gérer les requêtes utilisateur.
        Permet d'intercepter les demandes de création d'agents.
        """
        q = query.lower()
        # Détection des requêtes de création
        for prefix in ["crée un agent", "créer un agent", "génère un agent", "fabrique un agent"]:
            if prefix in q:
                # Extraire la description (tout ce qui suit le préfixe)
                description = q.split(prefix, 1)[1].strip()
                if description:
                    return await self._tool_create_agent(description=description)
                return "Décris l'agent que tu veux créer."
        # Sinon, comportement par défaut
        return await super().handle(query)

    # -----------------------------------------------------------------------
    # Implémentation des outils
    # -----------------------------------------------------------------------
    async def _tool_create_agent(self, description: str, name: Optional[str] = None) -> str:
        """
        Crée un nouvel agent à partir d'une description.
        [Évolution] Création de nouvelles entités adaptées aux besoins.
        [Symbiose] L'agent s'intègre dans l'écosystème existant.
        """
        logger.info(f"🧙 Création d'un agent à partir de la description : {description}")

        # 1. Utiliser le LLM pour générer le code de l'agent
        agent_code = await self._generate_agent_code(description, name)
        if not agent_code:
            raise ToolExecutionError("Impossible de générer le code de l'agent.")

        # 2. Extraire le nom de la classe générée (ou utiliser le nom fourni)
        class_name_match = re.search(r"class\s+(\w+)\s*\(", agent_code)
        if class_name_match:
            class_name = class_name_match.group(1)
        else:
            class_name = name or "GeneratedAgent"

        # 3. Sauvegarder le code dans un fichier
        filepath = self.agents_dir / f"{class_name.lower()}.py"
        if filepath.exists():
            # Éviter d'écraser un agent existant
            raise ToolExecutionError(f"Un agent nommé {class_name} existe déjà.")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(agent_code)

        logger.info(f"✅ Agent '{class_name}' créé dans {filepath}")

        # 4. Publier un événement pour informer le cortex qu'un nouvel agent est disponible
        self.event_bus.publish(
            "agent.created",
            {"name": class_name, "path": str(filepath)},
            self.name,
        )

        return f"✅ Agent '{class_name}' créé avec succès. Vous pouvez maintenant l'utiliser."

    async def _tool_list_agents(self) -> str:
        """Liste tous les agents créés."""
        files = list(self.agents_dir.glob("*.py"))
        if not files:
            return "📂 Aucun agent créé pour l'instant."
        result = "📂 Agents disponibles :\n"
        for f in files:
            # Lire la première ligne pour obtenir la docstring ou le nom de la classe
            with open(f, "r") as fp:
                first_line = fp.readline().strip()
            result += f"  - {f.stem} ({first_line})\n"
        return result

    async def _tool_delete_agent(self, name: str) -> str:
        """Supprime un agent créé."""
        filepath = self.agents_dir / f"{name.lower()}.py"
        if not filepath.exists():
            raise ToolExecutionError(f"Agent '{name}' introuvable.")
        filepath.unlink()
        logger.info(f"🗑️ Agent '{name}' supprimé.")
        return f"✅ Agent '{name}' supprimé."

    # -----------------------------------------------------------------------
    # Méthodes auxiliaires
    # -----------------------------------------------------------------------
    async def _generate_agent_code(self, description: str, name: Optional[str] = None) -> Optional[str]:
        """
        Utilise le LLM pour générer le code Python d'un agent à partir de la description.
        [Moindre action] Utilise le modèle le plus adapté pour générer du code.
        [Homéostasie] Gère les erreurs de génération.
        """
        # Récupérer la liste des outils disponibles dans le système
        # Pour l'instant, on utilise une liste statique, mais on pourrait la rendre dynamique
        available_tools = [
            "open_application",
            "type_text",
            "click",
            "move_mouse",
            "get_screenshot",
            "mail_compose",
            "safari_open_url",
            "arrange_windows",
            "create_word_document",
            "create_reminder",
            "web_search",
            "scan_file",
            "quarantine_file",
        ]

        prompt = f"""Tu es un générateur de code pour des agents IA. L'utilisateur veut créer un agent capable de :
{description}

Génère une classe Python complète pour cet agent. La classe doit hériter de `BaseAgent` et définir :
- `get_tools()` qui retourne une liste d'outils parmi ceux disponibles : {available_tools}
- `handle(self, query: str) -> str` qui implémente la logique spécifique de l'agent (si nécessaire, sinon peut renvoyer `await super().handle(query)`).
- Éventuellement des méthodes `_tool_*` supplémentaires si l'agent a besoin de logique interne (mais les outils de base sont déjà fournis).

Respecte les règles :
- Nom de classe : si un nom est fourni, utilise-le, sinon invente un nom pertinent (ex: WeatherAgent).
- Inclus des docstrings pour la classe et les méthodes.
- Utilise les imports nécessaires (de app.agents.base_agent import BaseAgent, Tool, etc.).
- Les paramètres des outils sont des dictionnaires ; ils seront validés par les contrats existants.

Réponds UNIQUEMENT avec le code Python, sans commentaires supplémentaires.
"""
        if name:
            prompt += f"\nNom souhaité pour la classe : {name}"

        try:
            # Utiliser le modèle "balanced" pour la génération de code
            response = await self.ask_llm_async(prompt, model="balanced", temperature=0.2, max_tokens=1500)
            # Nettoyer la réponse pour extraire le code
            code = response.strip()
            # Enlever les éventuels blocs markdown
            if code.startswith("```python"):
                code = code[9:]
            if code.endswith("```"):
                code = code[:-3]
            code = code.strip()
            return code
        except Exception as e:
            logger.error(f"Erreur lors de la génération du code : {e}")
            return None