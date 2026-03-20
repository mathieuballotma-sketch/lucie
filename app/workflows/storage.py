"""
WorkflowStorage — Persistance des workflows dans une base SQLite.

Table : workflows (id, name, description, data JSON, created_at, updated_at)
Thread-safe via connexion locale au thread.
"""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .schemas import Workflow, WorkflowEdge, WorkflowNode
from ..utils.logger import logger


# ── Sérialisation ─────────────────────────────────────────────────────────────

def _workflow_to_dict(workflow: Workflow) -> Dict:
    """Convertit un Workflow en dict JSON-sérialisable."""
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "version": workflow.version,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "nodes": [
            {
                "id": n.id,
                "node_type": n.node_type,
                "config": n.config,
                "position": n.position,
            }
            for n in workflow.nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source_node": e.source_node,
                "source_port": e.source_port,
                "target_node": e.target_node,
                "target_port": e.target_port,
            }
            for e in workflow.edges
        ],
    }


def _dict_to_workflow(data: Dict) -> Workflow:
    """Reconstruit un Workflow depuis un dict désérialisé."""
    nodes = [
        WorkflowNode(
            id=n["id"],
            node_type=n["node_type"],
            config=n.get("config", {}),
            position=n.get("position", {"x": 0, "y": 0}),
        )
        for n in data.get("nodes", [])
    ]
    edges = [
        WorkflowEdge(
            id=e["id"],
            source_node=e["source_node"],
            source_port=e["source_port"],
            target_node=e["target_node"],
            target_port=e["target_port"],
        )
        for e in data.get("edges", [])
    ]
    return Workflow(
        id=data["id"],
        name=data.get("name", ""),
        description=data.get("description", ""),
        nodes=nodes,
        edges=edges,
        version=data.get("version", "1.0"),
        created_at=data.get("created_at", datetime.now().isoformat()),
        updated_at=data.get("updated_at", datetime.now().isoformat()),
    )


# ── WorkflowStorage ───────────────────────────────────────────────────────────

class WorkflowStorage:
    """
    Persistance des workflows dans SQLite.

    Thread-safe : chaque thread obtient sa propre connexion via threading.local.
    Utilise INSERT ... ON CONFLICT pour un upsert propre.
    """

    def __init__(self, db_path: str = "workflows.db") -> None:
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Retourne une connexion SQLite locale au thread courant."""
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        """Crée la table workflows si elle n'existe pas."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                data        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
        conn.commit()
        logger.debug(f"WorkflowStorage: base initialisée ({self.db_path})")

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def save(self, workflow: Workflow) -> None:
        """Insère ou met à jour un workflow (upsert)."""
        workflow.updated_at = datetime.now().isoformat()
        data = json.dumps(_workflow_to_dict(workflow), ensure_ascii=False)
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO workflows (id, name, description, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name        = excluded.name,
                description = excluded.description,
                data        = excluded.data,
                updated_at  = excluded.updated_at
            """,
            (
                workflow.id,
                workflow.name,
                workflow.description,
                data,
                workflow.created_at,
                workflow.updated_at,
            ),
        )
        conn.commit()
        logger.info(f"WorkflowStorage: sauvegardé '{workflow.name}' ({workflow.id})")

    def load(self, workflow_id: str) -> Optional[Workflow]:
        """Charge un workflow par son ID. Retourne None si introuvable."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data FROM workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return _dict_to_workflow(json.loads(row["data"]))
        except Exception as e:
            logger.error(f"WorkflowStorage.load: erreur désérialisation — {e}")
            return None

    def list_all(self) -> List[Dict]:
        """Retourne la liste des workflows (id, name, description, updated_at)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, name, description, updated_at FROM workflows "
            "ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, workflow_id: str) -> bool:
        """Supprime un workflow. Retourne True si effectivement supprimé."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM workflows WHERE id = ?", (workflow_id,)
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"WorkflowStorage: supprimé {workflow_id}")
        return deleted

    # ── Import / Export ───────────────────────────────────────────────────────

    def export_json(self, workflow_id: str, output_path: str) -> bool:
        """Exporte un workflow en fichier JSON lisible. Retourne False si introuvable."""
        workflow = self.load(workflow_id)
        if workflow is None:
            logger.warning(f"WorkflowStorage.export_json: {workflow_id} introuvable")
            return False

        Path(output_path).write_text(
            json.dumps(_workflow_to_dict(workflow), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"WorkflowStorage: exporté → {output_path}")
        return True

    def import_json(self, path: str) -> Optional[Workflow]:
        """Charge et sauvegarde un workflow depuis un fichier JSON."""
        try:
            raw = Path(path).read_text(encoding="utf-8")
            data = json.loads(raw)
            workflow = _dict_to_workflow(data)
            self.save(workflow)
            logger.info(f"WorkflowStorage: importé '{workflow.name}' depuis {path}")
            return workflow
        except Exception as e:
            logger.error(f"WorkflowStorage.import_json({path}): {e}")
            return None
