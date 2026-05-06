#!/usr/bin/env python3
"""Génère la table de bornes d'articles depuis la base SQLite Légifrance.

Produit `lucie_v1_standalone/dialogue/article_bounds_data.py`, un module
Python pur contenant `ARTICLE_BOUNDS_DATA: dict[(prefix, base)] -> (min, max)`.

Ce fichier est versionné dans git et chargé en O(1) par `article_bounds.py`
au runtime — zéro I/O SQLite sur le hot path.

À régénérer après chaque sync DILA majeure (cf. legifrance_sync.py). Le
script tolère que la DB soit lente : il fait UNE seule requête full-scan.

Usage:
    python3 scripts/build_article_bounds.py             # génère + écrit
    python3 scripts/build_article_bounds.py --dry-run   # affiche stats sans écrire
    python3 scripts/build_article_bounds.py --check     # diff vs whitelist _RANGES
"""

from __future__ import annotations

import argparse
import datetime
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = (
    REPO_ROOT / "lucie_v1_standalone" / "dialogue" / "article_bounds_data.py"
)

# Format DB : "L1234-17", "L1234-17-1" (sub-suffix), "L1234" (sans suffix).
# On capture le suffixe principal (avant un éventuel sous-suffixe).
_NUM_RE = re.compile(r"^[LRD](\d{3,4})(?:-(\d+))?(?:-\d+)?$")


def get_db_path() -> Path:
    """Résout le chemin DB via la même logique que le runtime."""
    sys.path.insert(0, str(REPO_ROOT))
    from lucie_v1_standalone.config import get_legifrance_db_path

    return get_legifrance_db_path()


def scan_articles(db_path: Path) -> dict[tuple[str, int], tuple[int, int]]:
    """Scanne la DB et retourne {(prefix, base): (suffix_min, suffix_max)}.

    Considère seulement les articles en VIGUEUR avec un suffixe numérique
    parseable. Les articles sans suffixe ou avec format atypique sont ignorés.
    """
    print(f"[build_article_bounds] Connexion DB read-only : {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        t = time.perf_counter()
        rows = conn.execute(
            "SELECT num_prefix, num FROM articles "
            "WHERE etat = 'VIGUEUR' AND num_prefix IN ('L', 'R', 'D')"
        ).fetchall()
        print(
            f"[build_article_bounds] Fetch {len(rows)} articles VIGUEUR "
            f"en {(time.perf_counter()-t)*1000:.0f} ms"
        )
    finally:
        conn.close()

    bounds: dict[tuple[str, int], tuple[int, int]] = {}
    skipped = 0
    t = time.perf_counter()
    for prefix, num in rows:
        m = _NUM_RE.match(num)
        if m is None:
            skipped += 1
            continue
        base_str, suffix_str = m.group(1), m.group(2)
        if suffix_str is None:
            continue
        try:
            base = int(base_str)
            suffix = int(suffix_str)
        except ValueError:
            skipped += 1
            continue
        key = (prefix, base)
        cur = bounds.get(key)
        if cur is None:
            bounds[key] = (suffix, suffix)
        else:
            bounds[key] = (min(cur[0], suffix), max(cur[1], suffix))
    print(
        f"[build_article_bounds] Parse {len(bounds)} racines en "
        f"{(time.perf_counter()-t)*1000:.0f} ms (skipped: {skipped})"
    )
    return bounds


def render_module(bounds: dict[tuple[str, int], tuple[int, int]]) -> str:
    """Sérialise le dict en source Python (clés triées pour diff stable)."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    sorted_keys = sorted(bounds.keys())
    lines = [
        '"""AUTO-GENERATED par scripts/build_article_bounds.py — do not edit by hand.',
        "",
        "Source : SQLite Légifrance (table `articles`, etat='VIGUEUR').",
        "Régénérer après chaque sync DILA majeure :",
        "    python3 scripts/build_article_bounds.py",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f'GENERATED_AT = "{now}"',
        f"RACINES_COUNT = {len(bounds)}",
        "",
        "# {(prefix, base) -> (suffix_min, suffix_max)}",
        "ARTICLE_BOUNDS_DATA: dict[tuple[str, int], tuple[int, int]] = {",
    ]
    for key in sorted_keys:
        prefix, base = key
        smin, smax = bounds[key]
        lines.append(f'    ("{prefix}", {base}): ({smin}, {smax}),')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def cmd_check(bounds: dict[tuple[str, int], tuple[int, int]]) -> int:
    """Compare la table SQLite vs whitelist _RANGES (audit divergences)."""
    sys.path.insert(0, str(REPO_ROOT))
    from lucie_v1_standalone.dialogue.whitelist_ct import _RANGES

    wl_bounds: dict[tuple[str, int], tuple[int, int]] = {}
    for prefix, base, first, last in _RANGES:
        key = (prefix, base)
        cur = wl_bounds.get(key)
        if cur is None:
            wl_bounds[key] = (first, last)
        else:
            wl_bounds[key] = (min(cur[0], first), max(cur[1], last))

    only_in_sqlite = set(bounds) - set(wl_bounds)
    only_in_wl = set(wl_bounds) - set(bounds)
    common = set(bounds) & set(wl_bounds)
    diverging = [
        (k, wl_bounds[k], bounds[k]) for k in common if wl_bounds[k] != bounds[k]
    ]

    print(f"\nRacines dans SQLite (DILA) : {len(bounds)}")
    print(f"Racines dans whitelist _RANGES : {len(wl_bounds)}")
    print(f"Communes : {len(common)}")
    print(f"Seulement DILA : {len(only_in_sqlite)}")
    print(f"Seulement whitelist : {len(only_in_wl)}")
    print(f"Divergentes : {len(diverging)}")

    if diverging:
        print("\nTop 20 divergences (whitelist vs DILA) :")
        for key, wl, db in diverging[:20]:
            prefix, base = key
            print(
                f"  {prefix}.{base}-x : whitelist=[{wl[0]}-{wl[1]}], "
                f"dila=[{db[0]}-{db[1]}]"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit pas le fichier, affiche seulement les stats.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare DILA vs whitelist _RANGES, ne génère rien.",
    )
    args = parser.parse_args(argv)

    db_path = get_db_path()
    if not db_path.exists():
        print(f"❌ DB Légifrance introuvable : {db_path}", file=sys.stderr)
        print("   Lancer d'abord : python3 scripts/legifrance_sync.py --first-run", file=sys.stderr)
        return 1

    bounds = scan_articles(db_path)
    if not bounds:
        print("❌ Aucune borne extraite — DB vide ou format inattendu.", file=sys.stderr)
        return 1

    if args.check:
        return cmd_check(bounds)

    if args.dry_run:
        print(f"\n[dry-run] {len(bounds)} racines extraites — fichier NON écrit.")
        sample = sorted(bounds.items())[:10]
        for key, val in sample:
            print(f"  {key} → {val}")
        return 0

    src = render_module(bounds)
    TARGET_FILE.write_text(src, encoding="utf-8")
    print(f"\n✓ Écrit : {TARGET_FILE} ({len(bounds)} racines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
