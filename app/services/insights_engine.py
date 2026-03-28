"""
Moteur d'insights proactifs pour Agent Lucide.
Analyse periodiquement les donnees utilisateur (fichiers, rappels, patterns,
organisation) pour generer des insights utiles stockes en SQLite.
Chaque insight a un score de pertinence, une priorite et un mecanisme
de deduplication sur 24h.
"""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


class InsightType(str, Enum):
    """Categorie d'un insight."""

    FILES_UNFINISHED = "files_unfinished"
    REMINDERS_OVERDUE = "reminders_overdue"
    UNUSUAL_PATTERN = "unusual_pattern"
    ORGANIZATION = "organization"


class InsightPriority(str, Enum):
    """Niveau de priorite d'un insight."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Insight:
    """Un insight genere par l'engine."""

    insight_type: InsightType
    title: str
    content: str
    score: float
    priority: InsightPriority
    context: Dict[str, Any] = field(default_factory=dict)
    insight_id: Optional[int] = None


class InsightsEngine:
    """
    Genere, stocke et expose des insights proactifs bases sur les donnees
    utilisateur.

    Analyses disponibles :
    - Fichiers recemment modifies mais non finalises
    - Rappels en retard ou oublies
    - Patterns d'activite inhabituels
    - Suggestions d'organisation (dossiers encombres)

    Les insights sont stockes en SQLite avec deduplication 24h et expiration
    automatique a 7 jours.
    """

    DEDUP_WINDOW_HOURS: int = 24
    EXPIRY_DAYS: int = 7
    ANOMALY_THRESHOLD: float = 2.0       # ratio current/baseline declenchant une alerte
    CROWDED_FOLDER_THRESHOLD: int = 100  # fichiers dans un dossier
    UNFINISHED_KEYWORDS: List[str] = [
        "draft", "wip", "todo", "temp", "tmp",
        "brouillon", "ebauche", "ébauche",
    ]

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Initialise l'engine avec une base SQLite.

        Args:
            db_path: Chemin vers la BDD. Par defaut ./data/insights.db.
        """
        if db_path is None:
            data_dir = Path("./data")
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "insights.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()
        logger.info(f"InsightsEngine initialise ({db_path})")

    def _init_db(self) -> None:
        """Cree les tables et index si inexistants."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                score REAL NOT NULL,
                priority TEXT NOT NULL,
                context TEXT DEFAULT '{}',
                seen INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                expires_at REAL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_insights_seen ON insights(seen)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_insights_created ON insights(created_at)"
        )
        self._conn.commit()

    # ─────────────────────────────────────────────────────────────────────────
    # Stockage et deduplication
    # ─────────────────────────────────────────────────────────────────────────

    def _is_duplicate(self, insight_type: InsightType, title: str) -> bool:
        """Retourne True si un insight identique existe dans la fenetre de dedup."""
        threshold = time.time() - self.DEDUP_WINDOW_HOURS * 3600
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id FROM insights
                WHERE insight_type = ? AND title = ? AND created_at > ?
                """,
                (insight_type.value, title, threshold),
            ).fetchone()
        return row is not None

    def store_insight(self, insight: Insight) -> Optional[int]:
        """
        Stocke un insight en BDD apres verification de doublon.

        Args:
            insight: L'insight a persister.

        Returns:
            L'id SQLite insere, ou None si l'insight est un doublon.
        """
        if self._is_duplicate(insight.insight_type, insight.title):
            logger.debug(f"Insight doublon ignore: {insight.title}")
            return None

        ctx_json = json.dumps(insight.context)
        now = time.time()
        expires = now + self.EXPIRY_DAYS * 86400

        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO insights
                    (insight_type, title, content, score, priority,
                     context, seen, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    insight.insight_type.value,
                    insight.title,
                    insight.content,
                    insight.score,
                    insight.priority.value,
                    ctx_json,
                    now,
                    expires,
                ),
            )
            self._conn.commit()
            row_id: Optional[int] = cursor.lastrowid

        logger.debug(f"Insight stocke (id={row_id}): {insight.title}")
        return row_id

    # ─────────────────────────────────────────────────────────────────────────
    # Lecture
    # ─────────────────────────────────────────────────────────────────────────

    def get_pending_insights(
        self,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> List[Insight]:
        """
        Retourne les insights non vus, non expires, avec score >= min_score.

        Args:
            limit: Nombre maximum de resultats.
            min_score: Seuil de score minimum (0.0–1.0).

        Returns:
            Liste d'Insight triee par score decroissant.
        """
        now = time.time()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, insight_type, title, content, score, priority, context
                FROM insights
                WHERE seen = 0
                  AND (expires_at IS NULL OR expires_at > ?)
                  AND score >= ?
                ORDER BY score DESC, created_at DESC
                LIMIT ?
                """,
                (now, min_score, limit),
            ).fetchall()

        result: List[Insight] = []
        for row in rows:
            ctx: Dict[str, Any] = {}
            try:
                ctx = json.loads(row[6])
            except (json.JSONDecodeError, TypeError):
                pass
            result.append(
                Insight(
                    insight_id=row[0],
                    insight_type=InsightType(row[1]),
                    title=row[2],
                    content=row[3],
                    score=row[4],
                    priority=InsightPriority(row[5]),
                    context=ctx,
                )
            )
        return result

    def mark_seen(self, insight_id: int) -> None:
        """
        Marque un insight comme vu pour ne plus le proposer.

        Args:
            insight_id: Id SQLite de l'insight.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE insights SET seen = 1 WHERE id = ?",
                (insight_id,),
            )
            self._conn.commit()

    # ─────────────────────────────────────────────────────────────────────────
    # Analyseurs
    # ─────────────────────────────────────────────────────────────────────────

    def analyze_files(self, paths: List[str]) -> List[Insight]:
        """
        Detecte les fichiers recemment modifies portant des noms de brouillon.

        Args:
            paths: Liste de chemins fichiers a analyser.

        Returns:
            Insights de type FILES_UNFINISHED.
        """
        insights: List[Insight] = []
        now = time.time()
        recent_threshold = now - 7 * 86400  # 7 derniers jours

        for path_str in paths:
            p = Path(path_str)
            if not p.is_file():
                continue
            try:
                mtime = p.stat().st_mtime
                if mtime < recent_threshold:
                    continue
                name_lower = p.name.lower()
                if any(kw in name_lower for kw in self.UNFINISHED_KEYWORDS):
                    age_days = (now - mtime) / 86400
                    insights.append(
                        Insight(
                            insight_type=InsightType.FILES_UNFINISHED,
                            title=f"Fichier non finalise: {p.name}",
                            content=(
                                f"Le fichier '{p.name}' semble etre en cours "
                                f"(modifie il y a {age_days:.0f} jour(s)). "
                                "Veux-tu le finaliser ou l'archiver ?"
                            ),
                            score=min(1.0, 0.5 + age_days * 0.05),
                            priority=InsightPriority.MEDIUM,
                            context={"path": str(p), "mtime": mtime},
                        )
                    )
            except OSError:
                continue

        return insights

    def analyze_reminders(
        self,
        reminders: List[Dict[str, Any]],
    ) -> List[Insight]:
        """
        Detecte les rappels dont la date d'echeance est depassee.

        Args:
            reminders: Liste de dicts avec au moins les cles 'due_at' (float
                       Unix timestamp) et 'title' (str).

        Returns:
            Insights de type REMINDERS_OVERDUE.
        """
        insights: List[Insight] = []
        now = time.time()

        for reminder in reminders:
            due = reminder.get("due_at")
            if due is None:
                continue
            if due < now:
                overdue_hours = (now - due) / 3600
                title: str = str(reminder.get("title", "Rappel sans titre"))
                priority = (
                    InsightPriority.HIGH
                    if overdue_hours > 24
                    else InsightPriority.MEDIUM
                )
                insights.append(
                    Insight(
                        insight_type=InsightType.REMINDERS_OVERDUE,
                        title=f"Rappel en retard: {title}",
                        content=(
                            f"Le rappel '{title}' etait prevu il y a "
                            f"{overdue_hours:.0f} heure(s). "
                            "Veux-tu le reporter ou le marquer comme fait ?"
                        ),
                        score=min(1.0, 0.6 + overdue_hours * 0.02),
                        priority=priority,
                        context=reminder,
                    )
                )

        return insights

    def analyze_patterns(
        self,
        current_stats: Dict[str, int],
        baseline_stats: Dict[str, int],
    ) -> List[Insight]:
        """
        Detecte les metriques d'activite inhabituellement elevees.

        Un insight est genere si current >= baseline * ANOMALY_THRESHOLD.

        Args:
            current_stats: Valeurs observees aujourd'hui (metric -> count).
            baseline_stats: Valeurs moyennes de reference (metric -> count).

        Returns:
            Insights de type UNUSUAL_PATTERN.
        """
        insights: List[Insight] = []

        for metric, current_val in current_stats.items():
            baseline_val = baseline_stats.get(metric, 0)
            if baseline_val == 0:
                continue
            ratio = current_val / baseline_val
            if ratio >= self.ANOMALY_THRESHOLD:
                insights.append(
                    Insight(
                        insight_type=InsightType.UNUSUAL_PATTERN,
                        title=f"Activite inhabituelle: {metric}",
                        content=(
                            f"Tu as {current_val} '{metric}' aujourd'hui "
                            f"(habituel: {baseline_val}). Est-ce normal ?"
                        ),
                        score=min(1.0, 0.4 + ratio * 0.1),
                        priority=InsightPriority.MEDIUM,
                        context={
                            "metric": metric,
                            "current": current_val,
                            "baseline": baseline_val,
                            "ratio": ratio,
                        },
                    )
                )

        return insights

    def analyze_organization(
        self,
        folder_stats: List[Dict[str, Any]],
    ) -> List[Insight]:
        """
        Suggere des ameliorations pour les dossiers encombres.

        Args:
            folder_stats: Liste de dicts avec 'path' (str) et
                          'file_count' (int).

        Returns:
            Insights de type ORGANIZATION.
        """
        insights: List[Insight] = []

        for stat in folder_stats:
            path: str = str(stat.get("path", ""))
            count: int = int(stat.get("file_count", 0))
            if count >= self.CROWDED_FOLDER_THRESHOLD:
                insights.append(
                    Insight(
                        insight_type=InsightType.ORGANIZATION,
                        title=f"Dossier encombre: {Path(path).name}",
                        content=(
                            f"Le dossier '{path}' contient {count} fichiers. "
                            "Veux-tu que je t'aide a le reorganiser ?"
                        ),
                        score=min(1.0, 0.3 + count / 500),
                        priority=InsightPriority.LOW,
                        context=stat,
                    )
                )

        return insights

    # ─────────────────────────────────────────────────────────────────────────
    # Analyse complete
    # ─────────────────────────────────────────────────────────────────────────

    def run_full_analysis(
        self,
        files: Optional[List[str]] = None,
        reminders: Optional[List[Dict[str, Any]]] = None,
        current_stats: Optional[Dict[str, int]] = None,
        baseline_stats: Optional[Dict[str, int]] = None,
        folder_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Insight]:
        """
        Lance tous les analyseurs disponibles et stocke les insights generes.

        Seuls les insights non-doublons sont persistes. Les ids SQLite sont
        injectes dans les objets Insight retournes.

        Args:
            files: Chemins fichiers pour analyze_files.
            reminders: Rappels pour analyze_reminders.
            current_stats: Stats actuelles pour analyze_patterns.
            baseline_stats: Stats de reference pour analyze_patterns.
            folder_stats: Stats dossiers pour analyze_organization.

        Returns:
            Tous les insights generes (persistes ou non).
        """
        all_insights: List[Insight] = []

        if files is not None:
            all_insights.extend(self.analyze_files(files))

        if reminders is not None:
            all_insights.extend(self.analyze_reminders(reminders))

        if current_stats is not None and baseline_stats is not None:
            all_insights.extend(
                self.analyze_patterns(current_stats, baseline_stats)
            )

        if folder_stats is not None:
            all_insights.extend(self.analyze_organization(folder_stats))

        stored_count = 0
        for insight in all_insights:
            stored_id = self.store_insight(insight)
            if stored_id is not None:
                insight.insight_id = stored_id
                stored_count += 1

        logger.info(
            f"InsightsEngine: {len(all_insights)} insights generes, "
            f"{stored_count} stockes (autres: doublons)"
        )
        return all_insights

    # ─────────────────────────────────────────────────────────────────────────
    # Integration MorningBrief
    # ─────────────────────────────────────────────────────────────────────────

    def get_summary_for_briefing(self) -> str:
        """
        Retourne une section Insights formatee pour le briefing matinal.

        Marque automatiquement les insights retournes comme vus.

        Returns:
            Chaine multiligne, vide si aucun insight pertinent.
        """
        insights = self.get_pending_insights(limit=5, min_score=0.5)
        if not insights:
            return ""

        priority_symbol: Dict[str, str] = {
            "high": "!",
            "medium": "~",
            "low": ".",
        }
        lines = ["Insights:"]
        for insight in insights:
            symbol = priority_symbol.get(insight.priority.value, "~")
            lines.append(f"  [{symbol}] {insight.title}")
            if insight.insight_id is not None:
                self.mark_seen(insight.insight_id)

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # Maintenance
    # ─────────────────────────────────────────────────────────────────────────

    def purge_expired(self) -> int:
        """
        Supprime les insights dont la date d'expiration est depassee.

        Returns:
            Nombre d'insights supprimes.
        """
        now = time.time()
        with self._lock:
            result = self._conn.execute(
                "DELETE FROM insights WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            deleted: int = result.rowcount
            self._conn.commit()

        if deleted > 0:
            logger.info(f"InsightsEngine: {deleted} insights expires supprimes")
        return deleted

    def close(self) -> None:
        """Ferme la connexion SQLite."""
        self._conn.close()
