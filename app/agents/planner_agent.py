"""
Planner Agent - Planifie et exécute des tâches complexes en plusieurs étapes.
Version améliorée avec gestion des dépendances et exécution parallèle.
"""

import asyncio
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
    Agent capable de décomposer une requête complexe en un plan d'actions,
    et d'exécuter les étapes en respectant les dépendances (parallélisme possible).
    """

    def __init__(self, llm_service, bus, config: dict):
        super().__init__("PlannerAgent", llm_service, bus)
        self.agents: Dict[str, BaseAgent] = {}  # Sera injecté par le cortex
        self.max_steps = config.get("max_plan_steps", 5)

    def set_agents(self, agents: Dict[str, BaseAgent]):
        """Injecte la liste des agents disponibles."""
        self.agents = agents

    def can_handle(self, query: str) -> bool:
        return False

    def get_tools(self) -> list:
        return []

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
        Exécute un plan en respectant les dépendances.
        Les étapes indépendantes sont exécutées en parallèle.
        """
        if not steps:
            return "Aucune étape à exécuter."

        # Construire un graphe de dépendances
        step_dict = {step.id: step for step in steps}
        dependents = {step.id: [] for step in steps}  # étapes qui dépendent de step.id
        dependencies_count = {step.id: 0 for step in steps}  # nombre de dépendances non satisfaites

        for step in steps:
            if step.depends_on:
                for dep_id in step.depends_on:
                    if dep_id in step_dict:
                        dependents[dep_id].append(step.id)
                        dependencies_count[step.id] += 1
                    else:
                        logger.warning(f"Étape {step.id} dépend d'une étape inconnue {dep_id}, ignorée")

        # File d'attente des étapes prêtes (sans dépendances)
        ready = asyncio.Queue()
        for step_id, count in dependencies_count.items():
            if count == 0:
                await ready.put(step_id)

        results = {}
        errors = []

        async def worker():
            """Tâche qui exécute les étapes au fur et à mesure."""
            while True:
                try:
                    step_id = await asyncio.wait_for(ready.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    # Plus d'étapes à traiter ?
                    if ready.empty() and all(sid in results or sid in errors for sid in step_dict):
                        break
                    continue

                step = step_dict[step_id]
                agent = self.agents.get(step.agent)
                if not agent:
                    error_msg = f"❌ Étape {step.id}: Agent {step.agent} introuvable"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    # Marquer comme échoué et décrémenter les dépendants
                    for dep_id in dependents[step_id]:
                        dependencies_count[dep_id] -= 1
                        if dependencies_count[dep_id] == 0:
                            await ready.put(dep_id)
                    continue

                try:
                    logger.info(f"Exécution de l'étape {step.id}: {step.description}")
                    result = await agent.execute_tool(step.tool, step.parameters)
                    results[step_id] = f"✅ Étape {step.id}: {result}"
                except Exception as e:
                    error_msg = f"❌ Étape {step.id} échouée: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    # On peut décider d'arrêter le plan ou de continuer
                    # Ici on continue, mais on pourrait lever une exception

                # Une fois l'étape terminée, on libère les dépendants
                for dep_id in dependents[step_id]:
                    dependencies_count[dep_id] -= 1
                    if dependencies_count[dep_id] == 0:
                        await ready.put(dep_id)

        # Lancer plusieurs workers pour paralléliser
        workers = [asyncio.create_task(worker()) for _ in range(min(len(steps), 3))]
        await asyncio.gather(*workers)

        # Construire la réponse finale
        output = []
        for step in steps:
            if step.id in results:
                output.append(results[step.id])
            elif step.id in errors:
                output.append(errors[step.id])  # déjà dans errors, mais on peut l'ajouter
        if errors:
            output.append("⚠️ Certaines étapes ont échoué.")
        return "\n".join(output) if output else "Aucun résultat."