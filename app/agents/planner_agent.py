"""
Planner Agent - Planifie et exécute des tâches complexes en plusieurs étapes.
"""

import json
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


class PlanStep(BaseModel):
    id: str = Field(..., description="Identifiant unique de l'étape")
    agent: str = Field(..., description="Nom de l'agent à utiliser")
    tool: str = Field(..., description="Nom de l'outil à exécuter")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Paramètres de l'outil")
    description: str = Field(..., description="Description de l'étape")
    depends_on: Optional[List[str]] = Field(None, description="IDs des étapes dont dépend cette étape")


class PlannerAgent(BaseAgent):
    """
    Agent capable de décomposer une requête complexe en un plan d'actions.
    """

    def __init__(self, llm_service, bus, config: dict):
        super().__init__("PlannerAgent", llm_service, bus)
        self.agents: Dict[str, BaseAgent] = {}  # Sera injecté par le cortex
        self.max_steps = config.get("max_plan_steps", 5)

    def set_agents(self, agents: Dict[str, BaseAgent]):
        """Injecte la liste des agents disponibles."""
        self.agents = agents

    def can_handle(self, query: str) -> bool:
        """Le planner ne gère pas directement les requêtes utilisateur."""
        return False

    def get_tools(self) -> list:
        return []  # Pas d'outils exposés directement

    async def create_plan(self, query: str) -> List[PlanStep]:
        """
        Utilise le LLM pour générer un plan d'actions.
        """
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
            response = await self.ask_llm_async(prompt, model="balanced", temperature=0.3, max_tokens=1024)
            cleaned = response.strip()
            # Extraire le JSON
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            data = json.loads(cleaned)
            if not isinstance(data, list):
                logger.error(f"La réponse du planner n'est pas une liste: {data}")
                return []
            steps = [PlanStep(**step) for step in data]
            if len(steps) > self.max_steps:
                logger.warning(f"Plan trop long ({len(steps)} > {self.max_steps}), troncature")
                steps = steps[:self.max_steps]
            return steps
        except Exception as e:
            logger.error(f"Erreur lors de la création du plan: {e}")
            return []

    async def execute_plan(self, steps: List[PlanStep]) -> str:
        """
        Exécute un plan séquentiellement (ignorer les dépendances pour l'instant).
        """
        results = []
        for step in steps:
            agent = self.agents.get(step.agent)
            if not agent:
                results.append(f"❌ Étape {step.id}: Agent {step.agent} introuvable")
                continue
            try:
                logger.info(f"Exécution de l'étape {step.id}: {step.description}")
                result = await agent.execute_tool(step.tool, step.parameters)
                results.append(f"✅ Étape {step.id}: {result}")
            except Exception as e:
                results.append(f"❌ Étape {step.id} échouée: {e}")
                # Option : arrêter l'exécution
                break
        return "\n".join(results)