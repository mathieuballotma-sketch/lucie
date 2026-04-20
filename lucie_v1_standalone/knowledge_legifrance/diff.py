"""
Diff human-readable entre deux syncs Légifrance.

Utilisé par `sync.py` pour générer un résumé court des changements
(ajoutés, modifiés, abrogés) à stocker dans l'AuditTrail.

Capé à 50 lignes dans l'audit (contrat : bref + consultable), mais le module
peut produire un diff complet pour usage debug.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


MAX_AUDIT_LINES = 50


@dataclass
class SyncDiff:
    added: list[str] = field(default_factory=list)       # "L1233-1 (Code du travail)"
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    abrogated: list[str] = field(default_factory=list)   # passages VIGUEUR → ABROGE

    @property
    def total(self) -> int:
        return (
            len(self.added)
            + len(self.updated)
            + len(self.deleted)
            + len(self.abrogated)
        )

    def summary_lines(self, max_lines: int = MAX_AUDIT_LINES) -> list[str]:
        """Lignes compactes, tronquées à `max_lines` pour l'audit."""
        lines = [
            f"+ {len(self.added)} articles ajoutés",
            f"~ {len(self.updated)} articles modifiés",
            f"× {len(self.abrogated)} articles abrogés",
            f"- {len(self.deleted)} articles supprimés",
        ]
        budget = max_lines - len(lines)
        samples: list[str] = []
        for label, items in [
            ("+", self.added),
            ("~", self.updated),
            ("×", self.abrogated),
            ("-", self.deleted),
        ]:
            for item in items:
                if len(samples) >= budget:
                    break
                samples.append(f"{label} {item}")
        if samples:
            lines.append("")
            lines.extend(samples)
        if self.total > len(samples):
            lines.append(f"… ({self.total - len(samples)} lignes tronquées)")
        return lines


def _article_map(conn: sqlite3.Connection) -> dict[str, tuple[str, str, int, str]]:
    """id → (num, code_titre, mtime, etat)."""
    cur = conn.execute(
        """
        SELECT a.id, a.num, COALESCE(c.titre, a.code_cid) AS titre, a.mtime, a.etat
          FROM articles a
          LEFT JOIN codes c ON c.cid = a.code_cid
        """
    )
    return {row[0]: (row[1], row[2], row[3] or 0, row[4]) for row in cur.fetchall()}


def compute_diff(
    conn_before: sqlite3.Connection | None,
    conn_after: sqlite3.Connection,
) -> SyncDiff:
    """
    Compare deux états de la base. Si `conn_before is None` (first-run),
    tous les articles `after` sont comptés comme `added`.
    """
    diff = SyncDiff()
    after = _article_map(conn_after)

    if conn_before is None:
        for art_id, (num, titre, _, _) in after.items():
            diff.added.append(f"{num} ({titre})")
        return diff

    before = _article_map(conn_before)
    before_ids = set(before)
    after_ids = set(after)

    for art_id in after_ids - before_ids:
        num, titre, _, _ = after[art_id]
        diff.added.append(f"{num} ({titre})")

    for art_id in before_ids - after_ids:
        num, titre, _, _ = before[art_id]
        diff.deleted.append(f"{num} ({titre})")

    for art_id in before_ids & after_ids:
        num_b, titre_b, mtime_b, etat_b = before[art_id]
        num_a, titre_a, mtime_a, etat_a = after[art_id]
        if etat_b == "VIGUEUR" and etat_a != "VIGUEUR":
            diff.abrogated.append(f"{num_a} ({titre_a})")
        elif mtime_a != mtime_b:
            diff.updated.append(f"{num_a} ({titre_a})")

    return diff
