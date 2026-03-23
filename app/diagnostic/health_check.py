"""
Vérification de santé de tous les composants de Lucie.

Vérifie : Ollama, modèles LLM, SQLite, index FAISS, espace disque, RAM, agents.
Lance un bilan complet au démarrage et toutes les heures en arrière-plan.

Principes :
- Homéostasie : détection proactive des défaillances
- Entropie     : rapport structuré, lisible, exploitable
- Évolution    : auto_fix() propose des correctifs concrets
"""

import asyncio
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from app.utils.logger import logger

# ---------------------------------------------------------------------------
# Seuils d'alerte
# ---------------------------------------------------------------------------
DISK_WARN_GB: float = 5.0    # Espace disque libre minimum recommandé (Go)
RAM_WARN_MB: float = 500.0   # RAM disponible minimum recommandée (Mo)


# ---------------------------------------------------------------------------
# HealthCheck
# ---------------------------------------------------------------------------

class HealthCheck:
    """
    Vérifie l'état de santé de tous les composants de Lucie.

    Retourne un rapport structuré et tente des corrections automatiques
    pour les problèmes les plus courants.
    """

    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        data_dir: Optional[str] = None,
        required_models: Optional[List[str]] = None,
    ) -> None:
        """
        Args:
            ollama_host:      URL de l'API Ollama locale.
            data_dir:         dossier de données de Lucie (pour SQLite / FAISS).
            required_models:  liste des noms de modèles requis (ex: ["qwen2.5:7b"]).
        """
        self.ollama_host = ollama_host
        self.data_dir = Path(data_dir) if data_dir else Path("./data")
        self.required_models: List[str] = required_models or []
        # Agents injectés optionnellement par l'engine après init
        self._agents: Optional[Dict[str, Any]] = None

    def set_agents(self, agents: Dict[str, Any]) -> None:
        """
        Injecte la liste des agents pour vérification.

        Args:
            agents: dict {nom_agent: instance_ou_None}.
        """
        self._agents = agents

    # ------------------------------------------------------------------
    # Bilan complet
    # ------------------------------------------------------------------

    async def check_all(self) -> Dict[str, Any]:
        """
        Vérifie l'ensemble des composants et retourne un rapport.

        Returns:
            dict avec une clé par composant, chacune contenant
            {"status": "ok"|"warning"|"error", "detail": str}.
            La clé "_global" résume l'état général.
        """
        logger.info("🩺 Démarrage du diagnostic complet…")

        results = await asyncio.gather(
            self._check_ollama(),
            self._check_models(),
            self._check_sqlite(),
            self._check_faiss(),
            self._check_disk_space(),
            self._check_memory(),
            self._check_agents(),
            return_exceptions=True,
        )

        keys = ["ollama", "models", "sqlite", "faiss", "disk", "memory", "agents"]
        report: Dict[str, Any] = {}
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                report[key] = {"status": "error", "detail": str(result)}
            else:
                report[key] = result

        # Résumé global
        statuses = [r.get("status", "error") for r in report.values()]
        if all(s == "ok" for s in statuses):
            report["_global"] = "ok"
        elif any(s == "error" for s in statuses):
            report["_global"] = "error"
        else:
            report["_global"] = "warning"

        logger.info(f"🩺 Diagnostic terminé — état global : {report['_global']}")
        return report

    # ------------------------------------------------------------------
    # Vérifications individuelles
    # ------------------------------------------------------------------

    async def _check_ollama(self) -> Dict[str, str]:
        """Ping Ollama sur localhost:11434."""
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.ollama_host}/api/tags") as resp:
                    if resp.status == 200:
                        return {
                            "status": "ok",
                            "detail": f"Ollama répond ({self.ollama_host})",
                        }
                    return {
                        "status": "error",
                        "detail": f"Ollama répond HTTP {resp.status}",
                    }
        except asyncio.TimeoutError:
            return {"status": "error", "detail": "Ollama timeout (>5 s)"}
        except Exception as exc:
            return {"status": "error", "detail": f"Ollama inaccessible : {exc}"}

    async def _check_models(self) -> Dict[str, Any]:
        """Vérifie que les modèles requis sont installés dans Ollama."""
        if not self.required_models:
            return {"status": "ok", "detail": "Aucun modèle requis configuré"}
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.ollama_host}/api/tags") as resp:
                    if resp.status != 200:
                        return {
                            "status": "error",
                            "detail": "Impossible de lister les modèles",
                        }
                    data = await resp.json()
                    installed = {m.get("name", "") for m in data.get("models", [])}
                    missing = [m for m in self.required_models if m not in installed]
                    if missing:
                        return {
                            "status": "warning",
                            "detail": f"Modèles manquants : {', '.join(missing)}",
                            "missing": missing,
                        }
                    return {
                        "status": "ok",
                        "detail": f"{len(self.required_models)} modèle(s) disponible(s)",
                    }
        except Exception as exc:
            return {
                "status": "error",
                "detail": f"Vérification modèles échouée : {exc}",
            }

    async def _check_sqlite(self) -> Dict[str, str]:
        """Vérifie l'accessibilité de la base SQLite épisodique."""
        db_path = self.data_dir / "episodic" / "episodic.db"
        try:
            import aiosqlite  # import local pour éviter dépendance circulaire

            if not db_path.exists():
                return {
                    "status": "warning",
                    "detail": f"Base SQLite absente : {db_path}",
                }
            async with aiosqlite.connect(str(db_path)) as db:
                async with db.execute("SELECT COUNT(*) FROM episodes") as cursor:
                    row = await cursor.fetchone()
                    count = int(row[0]) if row else 0
            return {"status": "ok", "detail": f"SQLite OK — {count} épisode(s) stocké(s)"}
        except Exception as exc:
            return {"status": "error", "detail": f"SQLite inaccessible : {exc}"}

    async def _check_faiss(self) -> Dict[str, str]:
        """Vérifie si un index FAISS est présent (RAG ou cache)."""
        rag_index = Path("./rag_data/faiss.index")
        cache_index = self.data_dir / "cache" / "faiss.index"
        try:
            if rag_index.exists():
                size_mb = rag_index.stat().st_size / (1024 * 1024)
                return {
                    "status": "ok",
                    "detail": f"Index FAISS RAG présent ({size_mb:.1f} Mo)",
                }
            if cache_index.exists():
                size_mb = cache_index.stat().st_size / (1024 * 1024)
                return {
                    "status": "ok",
                    "detail": f"Index FAISS cache présent ({size_mb:.1f} Mo)",
                }
            return {
                "status": "warning",
                "detail": "Aucun index FAISS trouvé — RAG non initialisé",
            }
        except Exception as exc:
            return {"status": "error", "detail": f"Vérification FAISS échouée : {exc}"}

    async def _check_disk_space(self) -> Dict[str, str]:
        """Vérifie l'espace disque disponible."""
        try:
            usage = shutil.disk_usage(str(self.data_dir.parent))
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            if free_gb < DISK_WARN_GB:
                return {
                    "status": "warning",
                    "detail": (
                        f"Espace disque faible : {free_gb:.1f} Go libre"
                        f" sur {total_gb:.0f} Go"
                    ),
                }
            return {
                "status": "ok",
                "detail": f"Disque OK — {free_gb:.1f} Go libre sur {total_gb:.0f} Go",
            }
        except Exception as exc:
            return {"status": "error", "detail": f"Vérification disque échouée : {exc}"}

    async def _check_memory(self) -> Dict[str, str]:
        """Vérifie la mémoire RAM disponible."""
        try:
            import psutil  # import local : psutil peut être absent
            mem = psutil.virtual_memory()
            available_mb = mem.available / (1024 ** 2)
            total_mb = mem.total / (1024 ** 2)
            if available_mb < RAM_WARN_MB:
                return {
                    "status": "warning",
                    "detail": (
                        f"RAM faible : {available_mb:.0f} Mo disponible"
                        f" sur {total_mb:.0f} Mo"
                    ),
                }
            return {
                "status": "ok",
                "detail": (
                    f"RAM OK — {available_mb:.0f} Mo disponible"
                    f" sur {total_mb:.0f} Mo"
                ),
            }
        except ImportError:
            return {"status": "warning", "detail": "psutil non disponible (RAM non vérifiée)"}
        except Exception as exc:
            return {"status": "error", "detail": f"Vérification RAM échouée : {exc}"}

    async def _check_agents(self) -> Dict[str, str]:
        """Vérifie que les agents principaux sont chargés."""
        agents = self._agents
        if agents is None:
            return {"status": "warning", "detail": "Liste des agents non injectée"}
        loaded = [name for name, agent in agents.items() if agent is not None]
        missing = [name for name, agent in agents.items() if agent is None]
        if missing:
            return {
                "status": "warning",
                "detail": (
                    f"{len(loaded)} agent(s) chargé(s), "
                    f"manquants : {', '.join(missing)}"
                ),
            }
        return {
            "status": "ok",
            "detail": f"{len(loaded)} agent(s) chargé(s) : {', '.join(loaded)}",
        }

    # ------------------------------------------------------------------
    # Corrections automatiques
    # ------------------------------------------------------------------

    async def auto_fix(self, issues: Dict[str, Any]) -> Dict[str, str]:
        """
        Tente de résoudre automatiquement les problèmes détectés.

        Args:
            issues: rapport issu de check_all().

        Returns:
            dict des actions tentées ou suggérées par composant.
        """
        actions: Dict[str, str] = {}

        # Ollama down → suggestion de redémarrage
        ollama_issue = issues.get("ollama", {})
        if ollama_issue.get("status") == "error":
            logger.warning("⚠️ Ollama inaccessible — suggestion de redémarrage")
            actions["ollama"] = (
                "Ollama semble arrêté.\n"
                "• Lancez : ollama serve\n"
                "• Ou relancez : brew services restart ollama"
            )

        # Modèle manquant → ollama pull
        models_issue = issues.get("models", {})
        if models_issue.get("status") == "warning":
            missing = models_issue.get("missing", [])
            for model in missing:
                actions[f"model_{model}"] = f"Installez le modèle : ollama pull {model}"

        # Espace disque faible → suggestions de nettoyage
        disk_issue = issues.get("disk", {})
        if disk_issue.get("status") == "warning":
            actions["disk"] = (
                "Espace disque faible. Suggestions :\n"
                "• Supprimez les modèles inutilisés : ollama rm <nom>\n"
                "• Videz ~/AgentLucide/quarantine/ si présent\n"
                "• Vérifiez les logs dans ./logs/"
            )

        return actions

    # ------------------------------------------------------------------
    # Formatage du rapport
    # ------------------------------------------------------------------

    def format_report(self, report: Dict[str, Any]) -> str:
        """
        Formate le rapport de diagnostic en markdown lisible.

        Args:
            report: issu de check_all().

        Returns:
            texte markdown formaté.
        """
        icons = {"ok": "✅", "warning": "⚠️", "error": "❌"}
        global_status = report.get("_global", "?")
        lines = [
            f"## 🩺 Diagnostic Lucie — "
            f"{icons.get(global_status, '?')} {global_status.upper()}",
            "",
        ]
        labels = {
            "ollama":  "Ollama",
            "models":  "Modèles LLM",
            "sqlite":  "Mémoire SQLite",
            "faiss":   "Index FAISS",
            "disk":    "Espace disque",
            "memory":  "RAM",
            "agents":  "Agents",
        }
        for key, label in labels.items():
            check = report.get(key, {})
            status = check.get("status", "?")
            detail = check.get("detail", "—")
            icon = icons.get(status, "?")
            lines.append(f"**{icon} {label}** : {detail}")

        return "\n".join(lines)
