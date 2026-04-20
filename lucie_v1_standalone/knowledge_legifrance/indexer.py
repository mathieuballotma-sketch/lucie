"""
Indexer thème → articles.

Matérialise la table `articles_by_theme` à partir de `theme_mapping.yaml`
et de la table `articles` déjà peuplée par `parser.apply_archive()`.

Règle de matching (simple, auditable) :
- Pour chaque thème, chaque code listé, chaque filtre `(prefix, range)` :
  - SELECT articles WHERE code_cid = ? AND num_prefix = ? AND num_numeric
    BETWEEN ? AND ?
  - Uniquement `etat = 'VIGUEUR'` (l'index ne contient pas les abrogés —
    pour les abrogés, l'agent passe par le retrieval full-text global).

Idempotent : clear + reinsert à chaque appel. Pas d'ADD delta.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

THEME_MAPPING_PATH = Path(__file__).parent / "theme_mapping.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    """
    Loader YAML minimal stdlib — on supporte uniquement le sous-ensemble
    utilisé dans `theme_mapping.yaml` (clés simples, listes, ranges [a,b],
    strings quoted ou non, commentaires `#`).

    On tente PyYAML d'abord (dépendance projet), fallback sur parseur maison
    si PyYAML absent (utile en test unitaire isolé).
    """
    try:
        import yaml  # type: ignore[import-untyped]

        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        logger.warning("PyYAML absent, fallback parser minimal")
        return _parse_yaml_minimal(path.read_text(encoding="utf-8"))


def _parse_yaml_minimal(src: str) -> dict[str, Any]:
    """
    Parseur YAML minimal — supporte uniquement la forme attendue du fichier
    `theme_mapping.yaml`. Jamais utilisé en production (PyYAML est listé en
    requirements) ; c'est une bouée pour les tests sans deps.

    Syntaxe acceptée :
        version: "1.0"
        themes:
          foo:
            libelle: "..."
            codes:
              - id: LEGITEXTxxxx
                filtres_articles:
                  - prefix: "L"
                    range: [1, 99]
            mots_cles:
              - alpha
              - beta
    """
    import re

    lines = src.splitlines()

    def _depth(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _strip_quotes(s: str) -> str:
        s = s.strip()
        if (s.startswith('"') and s.endswith('"')) or (
            s.startswith("'") and s.endswith("'")
        ):
            return s[1:-1]
        return s

    def _parse_value(raw: str) -> Any:
        raw = raw.strip()
        if raw == "":
            return None
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            if not inner:
                return []
            return [_parse_value(x) for x in inner.split(",")]
        if re.fullmatch(r"-?\d+", raw):
            return int(raw)
        if re.fullmatch(r"-?\d+\.\d+", raw):
            return float(raw)
        return _strip_quotes(raw)

    # Filtre commentaires et lignes vides
    filtered: list[tuple[int, str]] = []
    for raw_line in lines:
        stripped = raw_line.split("#", 1)[0].rstrip()
        if not stripped.strip():
            continue
        filtered.append((_depth(stripped), stripped))

    def parse_block(
        start: int, base_indent: int
    ) -> tuple[Any, int]:
        """Retourne (valeur, index_ligne_suivante)."""
        # Cas liste : toutes les lignes commencent par '- '
        if filtered[start][1].lstrip().startswith("- "):
            items = []
            i = start
            while i < len(filtered) and filtered[i][0] == base_indent and filtered[
                i
            ][1].lstrip().startswith("- "):
                # Ligne : "- key: value" ou "- bare_value"
                content = filtered[i][1].lstrip()[2:]  # retire "- "
                if ":" in content and not content.startswith("["):
                    # Début d'un dict item
                    key, _, rest = content.partition(":")
                    key = key.strip()
                    rest = rest.strip()
                    item: dict[str, Any] = {}
                    if rest:
                        item[key] = _parse_value(rest)
                    # Sous-clés éventuelles (indent > base_indent + 2)
                    i += 1
                    while i < len(filtered) and filtered[i][0] > base_indent:
                        sub_indent = filtered[i][0]
                        sub_line = filtered[i][1].lstrip()
                        if sub_line.startswith("- "):
                            # Sous-liste : remonte d'un niveau
                            break
                        if ":" in sub_line:
                            sk, _, sv = sub_line.partition(":")
                            sk = sk.strip()
                            sv = sv.strip()
                            if sv:
                                item[sk] = _parse_value(sv)
                            else:
                                # Bloc enfant
                                child, i = parse_block(i + 1, sub_indent + 2)
                                item[sk] = child
                                continue
                        i += 1
                    items.append(item)
                else:
                    items.append(_parse_value(content))
                    i += 1
            return items, i

        # Cas dict
        result: dict[str, Any] = {}
        i = start
        while i < len(filtered) and filtered[i][0] == base_indent:
            line = filtered[i][1].lstrip()
            if ":" not in line:
                break
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest:
                result[key] = _parse_value(rest)
                i += 1
            else:
                child, i = parse_block(i + 1, base_indent + 2)
                result[key] = child
        return result, i

    if not filtered:
        return {}
    result, _ = parse_block(0, 0)
    return result if isinstance(result, dict) else {"_root": result}


def load_theme_mapping(path: Path = THEME_MAPPING_PATH) -> dict[str, Any]:
    """Charge `theme_mapping.yaml`. Valide qu'on a bien `version` + `themes`."""
    data = _load_yaml(path)
    if not isinstance(data, dict) or "themes" not in data:
        raise ValueError(f"theme_mapping invalide (clé `themes` absente) : {path}")
    return data


def reindex_themes(
    conn: sqlite3.Connection,
    mapping: dict[str, Any] | None = None,
    include_non_vigueur: bool = False,
) -> dict[str, int]:
    """
    Recalcule `articles_by_theme` à partir de `articles` et du mapping.

    Retourne un dict `{theme_id: nb_articles_indexés}`.
    """
    if mapping is None:
        mapping = load_theme_mapping()
    themes = mapping.get("themes", {})
    counts: dict[str, int] = {}

    with conn:
        conn.execute("DELETE FROM articles_by_theme")
        for theme_id, theme_def in themes.items():
            total = 0
            for code in theme_def.get("codes", []):
                cid = code["id"]
                for filt in code.get("filtres_articles", []):
                    prefix = filt.get("prefix", "")
                    rng = filt.get("range") or [None, None]
                    lo, hi = rng[0], rng[1] if len(rng) > 1 else rng[0]

                    params: list[Any] = [theme_id, cid, prefix]
                    sql = (
                        "INSERT OR IGNORE INTO articles_by_theme (theme_id, article_id) "
                        "SELECT ?, id FROM articles "
                        "WHERE code_cid = ? AND num_prefix = ?"
                    )
                    if lo is not None and hi is not None:
                        sql += " AND num_numeric BETWEEN ? AND ?"
                        params += [lo, hi]
                    if not include_non_vigueur:
                        sql += " AND etat = 'VIGUEUR'"

                    cur = conn.execute(sql, params)
                    total += cur.rowcount if cur.rowcount >= 0 else 0
            counts[theme_id] = total
            logger.info("theme %s: %d articles indexés", theme_id, total)
    return counts
