"""
Rapport hebdomadaire d'activité de Lucie.

Agrège les données de mémoire épisodique et de feedback utilisateur
pour générer un récapitulatif lisible chaque dimanche soir.

Contient :
- Nombre de requêtes traitées dans la semaine
- Taux de satisfaction (via FeedbackCollector)
- Agents les plus sollicités
- Requêtes les plus mal notées (points faibles)
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import aiosqlite

from app.utils.logger import logger

if TYPE_CHECKING:
    from app.feedback.collector import FeedbackCollector


# ---------------------------------------------------------------------------
# WeeklyReport
# ---------------------------------------------------------------------------

class WeeklyReport:
    """
    Génère un récapitulatif hebdomadaire de l'activité de Lucie.

    Toutes les données sont extraites de SQLite (mémoire épisodique + feedback).
    Le rapport est formaté en markdown.
    """

    def __init__(
        self,
        episodic_db_path: Path,
        feedback_collector: Optional["FeedbackCollector"] = None,
    ) -> None:
        """
        Args:
            episodic_db_path:   chemin vers la base mémoire épisodique.
            feedback_collector: collecteur de feedback (optionnel).
        """
        self.episodic_db_path = episodic_db_path
        self.feedback_collector = feedback_collector

    # ------------------------------------------------------------------
    # Génération principale
    # ------------------------------------------------------------------

    async def generate(self) -> str:
        """
        Génère le rapport de la semaine passée.

        Returns:
            rapport formaté en markdown.
        """
        logger.info("📋 Génération du rapport hebdomadaire…")
        now = datetime.now()
        week_label = now.strftime("%d/%m/%Y")

        # Données épisodiques
        episode_count = await self._count_episodes_this_week()

        # Données de feedback
        fb_stats: Dict[str, Any] = {
            "total": 0, "positifs": 0, "negatifs": 0, "ratio": 0.0,
        }
        top_negatives: List[Dict[str, Any]] = []
        collector = self.feedback_collector
        if collector is not None:
            fb_stats = await collector.get_stats()
            top_negatives = await collector.get_negative_patterns(limit=5)

        # Agents les plus utilisés
        top_agents = await self._get_top_agents()

        # Construction du rapport
        satisfaction_pct = round(fb_stats["ratio"] * 100, 1)
        total_fb = fb_stats["total"]
        positifs = fb_stats["positifs"]
        negatifs = fb_stats["negatifs"]

        lines: List[str] = [
            f"## 📊 Rapport hebdomadaire — semaine du {week_label}",
            "",
            "### Activité",
            f"- **{episode_count}** requête(s) traitée(s) cette semaine",
            "",
            "### Satisfaction utilisateur",
        ]

        if total_fb > 0:
            lines += [
                f"- **{total_fb}** retour(s) reçu(s)",
                f"- 👍 {positifs} positif(s) · 👎 {negatifs} négatif(s)",
                f"- Taux de satisfaction : **{satisfaction_pct}%**",
            ]
        else:
            lines.append("- Aucun retour utilisateur cette semaine")

        if top_negatives:
            lines += [
                "",
                "### Points faibles détectés",
            ]
            for neg in top_negatives[:3]:
                count = neg.get("count", 0)
                query = str(neg.get("query_text", "?"))[:80]
                lines.append(f'- ❌ ({count}×) "{query}…"')

        if top_agents:
            lines += [
                "",
                "### Agents les plus sollicités",
            ]
            for agent_name, count in top_agents[:5]:
                lines.append(f"- **{agent_name}** : {count} fois")

        lines += [
            "",
            f"*Généré le {now.strftime('%d/%m/%Y à %H:%M')}*",
        ]

        report = "\n".join(lines)
        logger.info(
            f"📋 Rapport hebdomadaire généré — "
            f"{episode_count} épisodes, {total_fb} feedbacks"
        )
        return report

    # ------------------------------------------------------------------
    # Requêtes SQLite
    # ------------------------------------------------------------------

    async def _count_episodes_this_week(self) -> int:
        """Compte les épisodes mémoire de la semaine passée."""
        if not self.episodic_db_path.exists():
            return 0
        try:
            async with aiosqlite.connect(str(self.episodic_db_path)) as db:
                async with db.execute(
                    """
                    SELECT COUNT(*) FROM episodes
                    WHERE  timestamp >= datetime('now', '-7 days')
                    """
                ) as cursor:
                    row = await cursor.fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.error(f"Erreur comptage épisodes : {exc}")
            return 0

    async def _get_top_agents(self) -> List[tuple[str, int]]:
        """Récupère les agents les plus utilisés (via métadonnées épisodiques)."""
        if not self.episodic_db_path.exists():
            return []
        try:
            async with aiosqlite.connect(str(self.episodic_db_path)) as db:
                async with db.execute(
                    """
                    SELECT json_extract(metadata, '$.agent') AS agent,
                           COUNT(*)                           AS cnt
                    FROM   episodes
                    WHERE  timestamp >= datetime('now', '-7 days')
                      AND  json_extract(metadata, '$.agent') IS NOT NULL
                    GROUP  BY agent
                    ORDER  BY cnt DESC
                    LIMIT  10
                    """
                ) as cursor:
                    rows = await cursor.fetchall()
            return [(str(r[0]), int(r[1])) for r in rows if r[0]]
        except Exception as exc:
            logger.error(f"Erreur lecture agents épisodiques : {exc}")
            return []
