# app/agents/file_agent.py
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from app.agents.base_agent import BaseAgent
from app.utils.logger import logger


class FileAgent(BaseAgent):
    """
    Agent spécialisé dans la gestion des fichiers et dossiers.
    Peut lister, copier, déplacer, supprimer des fichiers et rechercher par contenu.
    """

    def __init__(self, llm_service: Any, bus: Any, config: dict[str, Any]) -> None:
        super().__init__("FileAgent", llm_service, bus)
        self.working_directory = config.get("working_directory", str(Path.home()))
        # Moteur de recherche — injecte par l'engine
        self.search_engine: Any = None
        logger.info(f"📁 Agent fichiers initialisé (dossier de travail: {self.working_directory})")

    def can_handle(self, query: str) -> bool:
        keywords = [
            "fichier", "dossier", "copie", "déplace",
            "supprime", "liste", "renomme", "backup", "sauvegarde",
            "cherche", "recherche", "trouve", "search", "find",
        ]
        return any(kw in query.lower() for kw in keywords)

    async def handle(self, query: str) -> str:
        prompt = f"""
Tu es un assistant qui gère des fichiers. Voici la demande de l'utilisateur :
"{query}"

Les actions disponibles sont :
- write : créer/écrire un fichier (path, content)
- list : lister les fichiers d'un dossier
- copy : copier un fichier (source, destination)
- move : déplacer un fichier (source, destination)
- delete : supprimer un fichier (chemin)
- rename : renommer un fichier (ancien_nouveau)

Le dossier de travail par défaut est : {self.working_directory}

Réponds UNIQUEMENT avec un JSON de cette forme :
{{
    "action": "nom_action",
    "params": {{
        "param1": "valeur1",
        ...
    }}
}}

Si la demande n'est pas claire, réponds {{"action": "unknown"}}.
"""
        try:
            response = self.ask_llm(prompt)
            cleaned = response.strip().replace("```json", "").replace("```", "").strip()
            try:
                decision = json.loads(cleaned)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", cleaned, re.DOTALL)
                if match:
                    decision = json.loads(match.group())
                else:
                    logger.warning(f"Réponse non JSON reçue: {cleaned[:100]}")
                    if "liste" in query.lower() or "list" in query.lower():
                        decision = {"action": "list", "params": {}}
                    elif "copie" in query.lower() or "copy" in query.lower():
                        decision = {"action": "copy", "params": {"source": "", "destination": ""}}
                    else:
                        return "Désolé, je n'ai pas compris votre demande. Pouvez-vous reformuler ?"

            action = decision.get("action")
            params = decision.get("params", {})

            if action == "unknown":
                return "Je n'ai pas compris quelle action sur les fichiers vous voulez effectuer."

            # Soumettre les actions à risque à ActionGate (niveau 2+)
            # list → level 1 (LOW) — pas de contrôle
            if action != "list":
                _gate_map = {
                    "write":  "write_file",
                    "copy":   "copy_file",
                    "move":   "move_file",
                    "delete": "delete_file",
                    "rename": "rename_file",
                }
                gate_type = _gate_map.get(action or "", "write_file")
                approved = await self.submit_action({
                    "action_type": gate_type,
                    "preview": f"{action} {params}",
                    "reversible": action not in ("delete",),
                })
                if not approved:
                    return f"⛔ Action '{action}' bloquée par ActionGate."

            return self.do_action(action or "unknown", params)

        except Exception as e:
            logger.error(f"Erreur dans FileAgent.handle: {e}")
            return f"Erreur lors du traitement: {str(e)}"

    def do_action(self, action: str, params: dict[str, Any]) -> str:
        """
        Exécute une action spécifique avec les paramètres donnés.

        FIX v2 : params.get() retourne Optional[str] — on passe "" comme défaut
        pour satisfaire les signatures qui attendent str.
        """
        if action == "list":
            return self._list_files(params.get("path") or self.working_directory)
        elif action == "write":
            return self._write_file(
                params.get("path") or "",
                params.get("content") or "",
            )
        elif action == "copy":
            return self._copy_file(
                params.get("source") or "",
                params.get("destination") or "",
            )
        elif action == "move":
            return self._move_file(
                params.get("source") or "",
                params.get("destination") or "",
            )
        elif action == "delete":
            return self._delete_file(params.get("path") or "")
        elif action == "rename":
            return self._rename_file(
                params.get("old") or "",
                params.get("new") or "",
            )
        else:
            return f"Action inconnue: {action}"

    def write_file(self, path: str, content: str) -> str:
        """Écrit du contenu dans un fichier (API directe pour le pipeline)."""
        return self._write_file(path, content)

    def _write_file(self, path: str, content: str) -> str:
        """Crée ou écrase un fichier avec le contenu donné."""
        if not path:
            return "Paramètre chemin manquant."
        if not content:
            return "Paramètre contenu manquant."
        try:
            p = Path(path).expanduser().resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            logger.info(f"Fichier écrit: {p} ({len(content)} caractères)")
            return f"✅ Fichier créé: {path} ({len(content)} caractères)"
        except Exception as e:
            return f"Erreur lors de l'écriture: {str(e)}"

    def _list_files(self, path: str) -> str:
        """Liste les fichiers d'un dossier."""
        try:
            p = Path(path).expanduser().resolve()
            if not p.exists():
                return f"Le dossier {path} n'existe pas."
            if not p.is_dir():
                return f"{path} n'est pas un dossier."

            files = list(p.iterdir())
            if not files:
                return f"Le dossier {path} est vide."

            result = f"Contenu de {path}:\n"
            for f in files:
                if f.is_dir():
                    result += f"📁 {f.name}/\n"
                else:
                    size = f.stat().st_size
                    result += f"📄 {f.name} ({size} octets)\n"
            return result
        except Exception as e:
            return f"Erreur lors du listage: {str(e)}"

    def _copy_file(self, source: str, dest: str) -> str:
        """Copie un fichier."""
        if not source or not dest:
            return "Paramètres source ou destination manquants."
        try:
            src = Path(source).expanduser().resolve()
            dst = Path(dest).expanduser().resolve()

            if not src.exists():
                return f"Le fichier source {source} n'existe pas."
            if src.is_dir():
                return "La copie de dossiers n'est pas encore supportée."

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.info(f"Fichier copié: {src} -> {dst}")
            return f"✅ Fichier copié avec succès vers {dest}"
        except Exception as e:
            return f"Erreur lors de la copie: {str(e)}"

    def _move_file(self, source: str, dest: str) -> str:
        """Déplace un fichier."""
        if not source or not dest:
            return "Paramètres source ou destination manquants."
        try:
            src = Path(source).expanduser().resolve()
            dst = Path(dest).expanduser().resolve()

            if not src.exists():
                return f"Le fichier source {source} n'existe pas."

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            logger.info(f"Fichier déplacé: {src} -> {dst}")
            return f"✅ Fichier déplacé avec succès vers {dest}"
        except Exception as e:
            return f"Erreur lors du déplacement: {str(e)}"

    def _delete_file(self, path: str) -> str:
        """Supprime un fichier."""
        if not path:
            return "Paramètre chemin manquant."
        try:
            p = Path(path).expanduser().resolve()
            if not p.exists():
                return f"Le fichier {path} n'existe pas."
            if p.is_dir():
                return "La suppression de dossiers n'est pas autorisée (trop risqué)."

            os.remove(p)
            logger.info(f"Fichier supprimé: {p}")
            return f"✅ Fichier supprimé: {path}"
        except Exception as e:
            return f"Erreur lors de la suppression: {str(e)}"

    def _rename_file(self, old: str, new: str) -> str:
        """Renomme un fichier."""
        if not old or not new:
            return "Paramètres ancien ou nouveau nom manquants."
        try:
            old_path = Path(old).expanduser().resolve()
            new_path = Path(new).expanduser().resolve()

            if not old_path.exists():
                return f"Le fichier {old} n'existe pas."

            old_path.rename(new_path)
            logger.info(f"Fichier renommé: {old} -> {new}")
            return f"✅ Fichier renommé: {new}"
        except Exception as e:
            return f"Erreur lors du renommage: {str(e)}"

    async def search(self, query: str, top_k: int = 10) -> str:
        """Recherche de fichiers par contenu via le moteur de recherche local."""
        engine = self.search_engine
        if engine is None:
            return "Le moteur de recherche n'est pas disponible."

        try:
            results = await engine.search(query, top_k=top_k)
            if not results:
                return f"Aucun fichier trouvé pour '{query}'."

            lines = [f"Résultats pour '{query}' ({len(results)} fichiers) :"]
            for r in results:
                score = r.get("score", 0)
                name = r.get("file_name", "?")
                summary = r.get("summary", "")
                path = r.get("file_path", "")
                line = f"  {'%.0f' % (score * 100)}% | {name}"
                if summary:
                    line += f" — {summary[:80]}"
                line += f"\n       {path}"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Erreur recherche: {e}")
            return f"Erreur lors de la recherche: {e}"
