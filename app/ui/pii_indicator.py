"""
Helpers de formatage pour le badge PII dans le HUD.

Formate les compteurs renvoyés par ``sanitizer.detect_pii()`` en libellés
discrets pour le badge agent-status-bar et la popover de détail.

Pure Python (pas de dépendance PyObjC) — facilite les tests unitaires.

Aucune valeur PII brute n'apparaît jamais dans la sortie ; uniquement les
catégories (NOM, EMAIL, SIRET, NIR, MONTANT, DATE, TEL, DOSSIER) et leurs
compteurs.
"""

from __future__ import annotations

from typing import Mapping


_LABEL_FR = {
    "NOM": "nom",
    "DOSSIER": "n° dossier",
    "MONTANT": "montant",
    "DATE": "date",
    "EMAIL": "email",
    "TEL": "téléphone",
    "SIRET": "SIRET",
    "NIR": "NIR",
}


def total_pii(counts: Mapping[str, int]) -> int:
    """Somme totale d'éléments PII détectés."""
    return sum(counts.values())


def format_badge_text(counts: Mapping[str, int]) -> str:
    """
    Texte du badge agent-status-bar.

    >>> format_badge_text({"EMAIL": 2, "SIRET": 1})
    '🔒 3 PII masquées'
    >>> format_badge_text({})
    '🔒 0 PII détectée'
    """
    n = total_pii(counts)
    if n == 0:
        return "🔒 0 PII détectée"
    if n == 1:
        return "🔒 1 PII masquée"
    return f"🔒 {n} PII masquées"


def format_popover_lines(counts: Mapping[str, int]) -> list[str]:
    """
    Lignes de la popover : "2 emails", "1 SIRET", … triées par count décroissant.

    Si counts vide : retourne une seule ligne "Aucune donnée personnelle détectée
    dans le dernier échange."
    """
    if not counts:
        return ["Aucune donnée personnelle détectée dans le dernier échange."]
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines: list[str] = []
    for category, n in items:
        label = _LABEL_FR.get(category, category.lower())
        suffix = "s" if n > 1 and not label.endswith(("s", "x")) else ""
        lines.append(f"{n} {label}{suffix}")
    return lines
