"""
WorkflowEditorAPI — Pont PyWebView entre le frontend React Flow et le backend Python.

Expose les méthodes CRUD et d'exécution pour l'éditeur visuel de workflows.
"""

import asyncio
import json
import os
import threading
from typing import Any, Dict, List, Optional

from ..utils.logger import logger
from .executor import WorkflowExecutor
from .node_registry import NodeRegistry
from .schemas import Workflow
from .storage import WorkflowStorage


class WorkflowEditorAPI:
    """API exposée au frontend via window.pywebview.api."""

    def __init__(
        self,
        storage: Optional[WorkflowStorage] = None,
        registry: Optional[NodeRegistry] = None,
        executor: Optional[WorkflowExecutor] = None,
    ) -> None:
        self._storage = storage or WorkflowStorage()
        if registry is None:
            self._registry = NodeRegistry()
            self._registry.auto_discover_agents()
        else:
            self._registry = registry
        self._executor = executor or WorkflowExecutor(registry=self._registry)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._start_event_loop()

    def _start_event_loop(self) -> None:
        """Démarre un event loop asyncio dans un thread dédié."""

        def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=_run_loop, args=(self._loop,), daemon=True
        )
        self._thread.start()

    def _run_async(self, coro: Any) -> Any:
        """Exécute une coroutine dans le thread asyncio et retourne le résultat."""
        loop = self._loop
        if loop is None:
            logger.error("WorkflowEditorAPI: event loop non initialisé")
            return None
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=30.0)

    def get_node_definitions(self) -> List[Dict[str, Any]]:
        """Retourne toutes les définitions de nœuds pour le frontend."""
        defs = self._registry.list_all()
        return [json.loads(d.json()) for d in defs]

    def get_node_categories(self) -> List[str]:
        """Retourne les catégories de nœuds disponibles."""
        return self._registry.categories()

    def save_workflow(self, data: Dict[str, Any]) -> str:
        """Sauvegarde un workflow. Retourne l'ID."""
        try:
            workflow = Workflow(**data)
            return self._storage.save(workflow)
        except Exception as exc:
            logger.error(f"WorkflowEditorAPI.save_workflow: {exc}")
            return ""

    def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Charge un workflow par ID."""
        wf = self._storage.load(workflow_id)
        if wf is None:
            return None
        result: Dict[str, Any] = json.loads(wf.json())
        return result

    def list_workflows(self) -> List[Dict[str, Any]]:
        """Liste tous les workflows sauvegardés."""
        workflows = self._storage.list_all()
        return [
            {"id": wf.id, "name": wf.name, "description": wf.description, "updated_at": wf.updated_at}
            for wf in workflows
        ]

    def delete_workflow(self, workflow_id: str) -> bool:
        """Supprime un workflow."""
        return self._storage.delete(workflow_id)

    def validate_workflow(self, data: Dict[str, Any]) -> List[str]:
        """Valide un workflow. Retourne la liste des erreurs (vide = OK)."""
        try:
            workflow = Workflow(**data)
            return self._executor.validate(workflow)
        except Exception as exc:
            return [str(exc)]

    def execute_workflow(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Exécute un workflow et retourne les résultats."""
        try:
            workflow = Workflow(**data)
            results = self._run_async(self._executor.execute(workflow))
            if results is None:
                return [{"node_id": "__error__", "status": "error", "error": "Event loop indisponible"}]
            return [json.loads(r.json()) for r in results]
        except Exception as exc:
            logger.error(f"WorkflowEditorAPI.execute_workflow: {exc}")
            return [{"node_id": "__error__", "status": "error", "error": str(exc)}]

    def shutdown(self) -> None:
        """Arrête l'event loop proprement."""
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            self._loop = None


def get_frontend_path() -> str:
    """Retourne le chemin vers le fichier index.html du frontend."""
    return os.path.join(os.path.dirname(__file__), "frontend", "index.html")


def launch_editor(
    title: str = "Lucie — Éditeur de Workflows",
    width: int = 1400,
    height: int = 900,
) -> None:
    """
    Lance l'éditeur de workflows dans une fenêtre PyWebView.

    Nécessite pywebview installé.
    """
    try:
        import webview
    except ImportError:
        logger.error("pywebview n'est pas installé. Installez-le avec: pip install pywebview")
        return

    api = WorkflowEditorAPI()
    frontend = get_frontend_path()

    if not os.path.exists(frontend):
        logger.error(f"Frontend introuvable : {frontend}")
        return

    webview.create_window(
        title,
        url=f"file://{frontend}",
        js_api=api,
        width=width,
        height=height,
        resizable=True,
        min_size=(800, 600),
    )
    webview.start()
    api.shutdown()
