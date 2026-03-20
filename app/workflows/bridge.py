"""
WorkflowEditorAPI — Pont PyWebView pour l'éditeur de flux visuel.

Expose une API Python au frontend JavaScript via window.pywebview.api.
Lance une fenêtre PyWebView chargée avec le frontend React Flow.
"""

import asyncio
import os
import threading
from typing import Any, Optional

from ..utils.logger import logger
from .executor import WorkflowExecutor
from .node_registry import NodeRegistry
from .schemas import Workflow
from .storage import WorkflowStorage

try:
    import webview  # type: ignore

    HAS_WEBVIEW = True
except ImportError:
    HAS_WEBVIEW = False
    logger.warning("WorkflowEditor: pywebview non installé — interface désactivée")


class WorkflowEditorAPI:
    """API exposée au frontend JavaScript via window.pywebview.api."""

    def __init__(
        self,
        storage: Optional[WorkflowStorage] = None,
        registry: Optional[NodeRegistry] = None,
    ) -> None:
        self.storage = storage or WorkflowStorage()
        self.registry = registry or NodeRegistry()
        self.executor = WorkflowExecutor(registry=self.registry)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._start_async_loop()

    def _start_async_loop(self) -> None:
        """Démarre la boucle asyncio dans un thread dédié."""
        loop = asyncio.new_event_loop()
        self._loop = loop

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=run_loop, daemon=True, name="workflow-async")
        self._thread = thread
        thread.start()

    def _run_async(self, coro: Any) -> Any:
        """Exécute une coroutine dans la boucle async dédiée (bloquant)."""
        loop = self._loop
        if loop is None:
            return None
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=30)
        except Exception as exc:
            logger.error(f"WorkflowEditorAPI: erreur async: {exc}")
            return None

    def get_node_definitions(self) -> list:
        """Retourne toutes les définitions de nœuds disponibles."""
        definitions = self.registry.list_all()
        result = []
        for node_def in definitions:
            result.append(
                {
                    "id": node_def.id,
                    "name": node_def.name,
                    "category": node_def.category,
                    "description": node_def.description,
                    "inputs": [
                        {
                            "name": p.name,
                            "type": p.type,
                            "description": p.description,
                            "required": p.required,
                        }
                        for p in node_def.inputs
                    ],
                    "outputs": [
                        {
                            "name": p.name,
                            "type": p.type,
                            "description": p.description,
                            "required": p.required,
                        }
                        for p in node_def.outputs
                    ],
                    "config_schema": node_def.config_schema,
                }
            )
        return result

    def save_workflow(self, data: dict) -> str:
        """Sauvegarde un workflow. Retourne l'ID ou chaîne vide en cas d'erreur."""
        try:
            workflow = Workflow.parse_obj(data)
            return self.storage.save(workflow)
        except Exception as exc:
            logger.error(f"WorkflowEditorAPI: erreur save_workflow: {exc}")
            return ""

    def load_workflow(self, workflow_id: str) -> Optional[dict]:
        """Charge un workflow par son ID. Retourne None si introuvable."""
        workflow = self.storage.load(workflow_id)
        if workflow is None:
            return None
        return workflow.dict()

    def list_workflows(self) -> list:
        """Liste tous les workflows sauvegardés (métadonnées uniquement)."""
        workflows = self.storage.list_all()
        return [
            {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "created_at": wf.created_at,
                "updated_at": wf.updated_at,
                "node_count": len(wf.nodes),
                "edge_count": len(wf.edges),
            }
            for wf in workflows
        ]

    def validate_workflow(self, data: dict) -> list:
        """Valide un workflow. Retourne la liste des erreurs (vide = valide)."""
        try:
            workflow = Workflow.parse_obj(data)
            return self.executor.validate(workflow)
        except Exception as exc:
            logger.error(f"WorkflowEditorAPI: erreur validate_workflow: {exc}")
            return [str(exc)]

    def execute_workflow(self, data: dict) -> list:
        """Exécute un workflow. Retourne les résultats nœud par nœud."""
        try:
            workflow = Workflow.parse_obj(data)
            results = self._run_async(self.executor.execute(workflow))
            if results is None:
                return []
            return [
                {
                    "node_id": r.node_id,
                    "status": r.status,
                    "output": r.output,
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                }
                for r in results
            ]
        except Exception as exc:
            logger.error(f"WorkflowEditorAPI: erreur execute_workflow: {exc}")
            return [{"node_id": "__error__", "status": "error", "error": str(exc)}]

    def shutdown(self) -> None:
        """Arrête proprement la boucle asyncio."""
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            self._loop = None


def launch_editor(
    registry: Optional[NodeRegistry] = None,
    storage: Optional[WorkflowStorage] = None,
    title: str = "Lucie — Éditeur de Flux",
    width: int = 1400,
    height: int = 900,
) -> None:
    """Lance l'éditeur de flux dans une fenêtre PyWebView."""
    if not HAS_WEBVIEW:
        logger.error("WorkflowEditor: pywebview requis — pip install pywebview")
        return

    api = WorkflowEditorAPI(storage=storage, registry=registry)
    html_path = os.path.join(os.path.dirname(__file__), "frontend", "index.html")

    try:
        window = webview.create_window(  # type: ignore[union-attr]
            title=title,
            url=f"file://{html_path}",
            js_api=api,
            width=width,
            height=height,
            min_size=(800, 600),
        )
        _ = window  # utilisé par pywebview internalement
        webview.start(debug=False)  # type: ignore[union-attr]
    finally:
        api.shutdown()
