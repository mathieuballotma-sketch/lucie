"""
Team Leader Agent - Dirige une équipe de sous-agents pour des tâches complexes.
"""

import asyncio
from typing import List, Dict, Any, Optional
from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger

class TeamLeaderAgent(BaseAgent):
    """
    Agent chef d'équipe. Peut créer des sous-agents (instances d'autres agents)
    et leur assigner des tâches en parallèle.
    """

    def __init__(self, llm_service, bus, config: dict):
        super().__init__("TeamLeaderAgent", llm_service, bus)
        self.agent_classes = {}  # mapping nom -> classe
        self.subagents = {}       # instances créées
        self.max_parallel = config.get("max_parallel_tasks", 3)

    def register_agent_class(self, name: str, agent_class):
        self.agent_classes[name] = agent_class

    async def create_subagent(self, agent_type: str, config: dict) -> BaseAgent:
        """Crée une instance d'un agent existant."""
        if agent_type not in self.agent_classes:
            raise ValueError(f"Type d'agent inconnu: {agent_type}")
        cls = self.agent_classes[agent_type]
        agent = cls(self.llm, self.bus, config)
        agent.event_bus = self.event_bus
        self.subagents[id(agent)] = agent
        return agent

    async def run_parallel(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """
        Exécute plusieurs tâches en parallèle.
        Chaque tâche : {'agent': agent_type, 'tool': tool_name, 'parameters': {...}}
        """
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def run_one(task):
            async with semaphore:
                agent_type = task['agent']
                tool = task['tool']
                params = task.get('parameters', {})
                # Chercher si l'agent existe déjà
                agent = None
                for a in self.subagents.values():
                    if a.name == agent_type:
                        agent = a
                        break
                if not agent:
                    agent = await self.create_subagent(agent_type, {})
                try:
                    result = await agent.execute_tool(tool, params)
                    return f"✅ {agent_type}.{tool}: {result}"
                except Exception as e:
                    return f"❌ {agent_type}.{tool}: {e}"

        results = await asyncio.gather(*[run_one(t) for t in tasks])
        return results

    def get_tools(self) -> list:
        return [
            Tool(
                name="run_team",
                description="Exécute plusieurs actions en parallèle avec une équipe d'agents.",
                contract=RunTeamContract,
            )
        ]

    async def _tool_run_team(self, tasks: List[Dict[str, Any]]) -> str:
        results = await self.run_parallel(tasks)
        return "\n".join(results)


# Contrat Pydantic
from pydantic import BaseModel, Field

class RunTeamContract(BaseModel):
    tasks: List[Dict[str, Any]] = Field(..., description="Liste des tâches à exécuter en parallèle")