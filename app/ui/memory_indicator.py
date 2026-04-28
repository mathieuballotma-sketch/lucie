"""
Helpers de formatage pour le badge MemoryStore dans le HUD.

Encapsule la lecture de ``MemoryStore.snapshot()`` (async) et le formatage
du badge + popover. Pure Python — testable sans PyObjC ni asyncio loop.

Aucune valeur PII brute n'est jamais retournée — uniquement les **types** de
nœuds (preference, skill, goal, relation, pattern) et leurs compteurs.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple


_NODE_TYPES_ORDER = ("preference", "skill", "goal", "relation", "pattern")
_TYPE_LABEL_FR = {
    "preference": "préférences",
    "skill": "compétences",
    "goal": "objectifs",
    "relation": "relations",
    "pattern": "schémas",
}


def extract_total_and_types(snapshot: Mapping[str, Any]) -> Tuple[int, Dict[str, int]]:
    """
    Extrait ``(total_nodes, {type: count})`` depuis ``MemoryStore.snapshot()``.

    Tolère les snapshots vides ou partiels.

    >>> snap = {"personal": {"preference": [{"content": "x"}], "_stats": {"total_nodes": 1}}}
    >>> extract_total_and_types(snap)
    (1, {'preference': 1, 'skill': 0, 'goal': 0, 'relation': 0, 'pattern': 0})
    """
    personal = snapshot.get("personal", {}) if snapshot else {}
    stats = personal.get("_stats", {}) if isinstance(personal, dict) else {}
    total = int(stats.get("total_nodes", 0) or 0)

    types: Dict[str, int] = {}
    for t in _NODE_TYPES_ORDER:
        items = personal.get(t, []) if isinstance(personal, dict) else []
        types[t] = len(items) if isinstance(items, list) else 0
    return total, types


def format_badge_text(total: int) -> str:
    """
    Texte du badge agent-status-bar.

    >>> format_badge_text(0)
    '🧠 Aucun souvenir'
    >>> format_badge_text(1)
    '🧠 1 souvenir'
    >>> format_badge_text(8)
    '🧠 8 souvenirs'
    """
    if total <= 0:
        return "🧠 Aucun souvenir"
    if total == 1:
        return "🧠 1 souvenir"
    return f"🧠 {total} souvenirs"


def format_popover_lines(types: Mapping[str, int]) -> list[str]:
    """
    Lignes de la popover : "3 préférences", "0 compétences", … dans l'ordre
    fixe (preference → skill → goal → relation → pattern).

    Inclut tous les types même à 0, pour une vue claire de la spécialisation.
    Ajoute une note finale "global, tous dossiers" car le schéma actuel ne
    supporte pas le filtre par dossier.
    """
    lines: list[str] = []
    for t in _NODE_TYPES_ORDER:
        n = int(types.get(t, 0) or 0)
        label = _TYPE_LABEL_FR.get(t, t)
        # Singulier : retire le "s" final
        if n == 1 and label.endswith("s"):
            label = label[:-1]
        lines.append(f"{n} {label}")
    lines.append("")  # ligne vide
    lines.append("(global, tous dossiers)")
    return lines
