"""Whitelist déterministe des codes du Code du travail.

Fallback utilisé par `ArticleResolver` quand la base Légifrance SQLite est
absente ou désactivée (mode dégradé). Garantit la promesse « refus <1s sur
article inexistant » même sans DB installée.

**Non exhaustif par construction.** Couvre ~400 codes des plages les plus
fréquemment citées en droit social (relations individuelles, contrat,
rupture, durée du travail, CSE, prud'hommes, santé-sécurité). Un article
obscur ou très récent absent d'ici sera faussement refusé si la DB
Légifrance n'est pas activée. D'où le WARNING démarrage : la whitelist est
un filet de sécurité, pas un remplacement.

Le canonical suit le format `article_validator.extract_article_codes` :
`"L1234-1"` (prefix collé, tiret avant suffixe) ou `"L1234"` (sans suffixe).
"""

from __future__ import annotations

from typing import Iterable


def _gen(prefix: str, base: int, first: int, last: int) -> Iterable[tuple[str, str]]:
    """Génère `(prefix, "L1234-N")` pour N de first à last inclus."""
    for n in range(first, last + 1):
        yield (prefix, f"{prefix}{base}-{n}")


# ─── Plages consolidées des articles CT les plus fréquents ──────────────────
# Format : (prefix, base_numeric, suffix_min, suffix_max)
#
# Plages bornées sur les divisions réelles du Code du travail. Les trous
# numériques éventuels à l'intérieur d'une plage sont tolérés (la whitelist
# peut inclure un code qui n'existe pas, auquel cas la DB Légifrance — quand
# elle sera activée — aura le dernier mot via la chaîne de résolveurs).
_RANGES: list[tuple[str, int, int, int]] = [
    # ── Partie L — Relations individuelles de travail ──
    ("L", 1111, 1, 3),
    ("L", 1121, 1, 1),
    ("L", 1131, 1, 2),
    ("L", 1132, 1, 4),
    ("L", 1133, 1, 6),
    ("L", 1134, 1, 10),
    ("L", 1141, 1, 1),
    ("L", 1142, 1, 6),
    ("L", 1143, 1, 3),
    ("L", 1144, 1, 3),
    ("L", 1146, 1, 3),
    ("L", 1151, 1, 1),
    ("L", 1152, 1, 6),
    ("L", 1153, 1, 6),
    ("L", 1154, 1, 2),
    ("L", 1155, 1, 2),
    ("L", 1161, 1, 1),
    # Contrat de travail
    ("L", 1221, 1, 26),
    ("L", 1222, 1, 11),
    ("L", 1223, 1, 5),
    ("L", 1224, 1, 9),
    ("L", 1225, 1, 72),
    ("L", 1226, 1, 24),
    # Rupture — règles générales
    ("L", 1231, 1, 7),
    # Licenciement motif personnel
    ("L", 1232, 1, 14),
    # Licenciement économique
    ("L", 1233, 1, 91),
    # Conséquences du licenciement
    ("L", 1234, 1, 20),
    # Contestation du licenciement
    ("L", 1235, 1, 18),
    # Ruptures diverses
    ("L", 1236, 1, 12),
    ("L", 1237, 1, 20),
    ("L", 1238, 1, 5),
    # CDD
    ("L", 1241, 1, 13),
    ("L", 1242, 1, 17),
    ("L", 1243, 1, 13),
    ("L", 1244, 1, 4),
    ("L", 1245, 1, 2),
    ("L", 1246, 1, 1),
    ("L", 1247, 1, 1),
    ("L", 1248, 1, 11),
    # Intérim
    ("L", 1251, 1, 64),
    ("L", 1253, 1, 24),
    ("L", 1254, 1, 9),
    ("L", 1255, 1, 18),
    # Portage
    ("L", 1254, 1, 9),
    # Détachement international
    ("L", 1261, 1, 3),
    ("L", 1262, 1, 5),
    ("L", 1263, 1, 7),
    ("L", 1264, 1, 3),
    # Règlement intérieur
    ("L", 1311, 1, 2),
    ("L", 1321, 1, 6),
    ("L", 1322, 1, 4),
    ("L", 1331, 1, 2),
    ("L", 1332, 1, 5),
    ("L", 1333, 1, 3),
    # Conseil des prud'hommes
    ("L", 1411, 1, 7),
    ("L", 1412, 1, 2),
    ("L", 1421, 1, 2),
    ("L", 1422, 1, 2),
    ("L", 1423, 1, 12),
    ("L", 1441, 1, 5),
    ("L", 1451, 1, 1),
    ("L", 1452, 1, 4),
    ("L", 1453, 1, 9),
    ("L", 1454, 1, 5),
    ("L", 1455, 1, 12),
    ("L", 1461, 1, 3),
    ("L", 1471, 1, 1),
    # ── Syndicats et représentation ──
    ("L", 2121, 1, 2),
    ("L", 2122, 1, 14),
    ("L", 2131, 1, 6),
    ("L", 2132, 1, 8),
    ("L", 2135, 1, 6),
    ("L", 2141, 1, 12),
    ("L", 2142, 1, 11),
    ("L", 2143, 1, 23),
    ("L", 2145, 1, 1),
    ("L", 2146, 1, 2),
    ("L", 2151, 1, 1),
    ("L", 2152, 1, 6),
    ("L", 2153, 1, 1),
    ("L", 2221, 1, 6),
    ("L", 2231, 1, 9),
    ("L", 2232, 1, 29),
    ("L", 2241, 1, 17),
    ("L", 2242, 1, 20),
    ("L", 2253, 1, 3),
    ("L", 2254, 1, 2),
    ("L", 2261, 1, 34),
    ("L", 2262, 1, 15),
    # CSE et dialogue social
    ("L", 2311, 1, 2),
    ("L", 2312, 1, 89),
    ("L", 2313, 1, 8),
    ("L", 2314, 1, 37),
    ("L", 2315, 1, 96),
    ("L", 2316, 1, 24),
    ("L", 2317, 1, 2),
    ("L", 2321, 1, 3),
    ("L", 2323, 1, 15),
    # Protection représentants
    ("L", 2411, 1, 25),
    ("L", 2412, 1, 15),
    ("L", 2413, 1, 1),
    ("L", 2421, 1, 9),
    ("L", 2431, 1, 3),
    ("L", 2432, 1, 2),
    # ── Durée du travail ──
    ("L", 3111, 1, 3),
    ("L", 3121, 1, 67),
    ("L", 3122, 1, 23),
    ("L", 3123, 1, 38),
    ("L", 3131, 1, 3),
    ("L", 3132, 1, 31),
    ("L", 3133, 1, 12),
    ("L", 3141, 1, 33),
    ("L", 3142, 1, 122),
    ("L", 3151, 1, 4),
    ("L", 3152, 1, 4),
    ("L", 3153, 1, 3),
    ("L", 3154, 1, 4),
    ("L", 3161, 1, 2),
    ("L", 3162, 1, 3),
    ("L", 3163, 1, 2),
    ("L", 3164, 1, 8),
    ("L", 3171, 1, 3),
    # ── Salaire ──
    ("L", 3221, 1, 9),
    ("L", 3231, 1, 12),
    ("L", 3232, 1, 9),
    ("L", 3241, 1, 8),
    ("L", 3242, 1, 5),
    ("L", 3243, 1, 5),
    ("L", 3244, 1, 2),
    ("L", 3245, 1, 2),
    ("L", 3246, 1, 2),
    ("L", 3251, 1, 4),
    ("L", 3252, 1, 13),
    ("L", 3253, 1, 24),
    ("L", 3261, 1, 5),
    ("L", 3262, 1, 7),
    # ── Santé et sécurité ──
    ("L", 4121, 1, 5),
    ("L", 4122, 1, 2),
    ("L", 4131, 1, 4),
    ("L", 4132, 1, 5),
    ("L", 4133, 1, 2),
    ("L", 4141, 1, 4),
    ("L", 4142, 1, 4),
    ("L", 4143, 1, 1),
    ("L", 4144, 1, 1),
    ("L", 4151, 1, 4),
    ("L", 4152, 1, 1),
    ("L", 4153, 1, 9),
    ("L", 4154, 1, 3),
    ("L", 4161, 1, 4),
    ("L", 4162, 1, 22),
    ("L", 4163, 1, 22),
    # ── Emploi, allocations chômage, formation ──
    ("L", 5111, 1, 3),
    ("L", 5112, 1, 1),
    ("L", 5141, 1, 7),
    ("L", 5411, 1, 10),
    ("L", 5412, 1, 2),
    ("L", 5421, 1, 4),
    ("L", 5422, 1, 25),
    ("L", 5423, 1, 38),
    ("L", 5424, 1, 23),
    ("L", 5425, 1, 10),
    ("L", 5426, 1, 9),
    # Formation professionnelle
    ("L", 6111, 1, 8),
    ("L", 6112, 1, 4),
    ("L", 6113, 1, 11),
    ("L", 6211, 1, 5),
    ("L", 6221, 1, 1),
    ("L", 6222, 1, 44),
    ("L", 6223, 1, 8),
    ("L", 6321, 1, 15),
    ("L", 6322, 1, 64),
    ("L", 6323, 1, 44),
    ("L", 6324, 1, 10),
    ("L", 6325, 1, 25),
    ("L", 6326, 1, 4),
    ("L", 6331, 1, 60),
    # ── Professions particulières (journalistes, artistes, VRP) ──
    ("L", 7111, 1, 10),
    ("L", 7112, 1, 5),
    ("L", 7113, 1, 4),
    ("L", 7121, 1, 8),
    ("L", 7122, 1, 4),
    ("L", 7123, 1, 6),
    ("L", 7311, 1, 3),
    ("L", 7313, 1, 18),
    # ── Partie R — Réglementaire (décrets Conseil d'État) ──
    ("R", 1221, 1, 39),
    ("R", 1232, 1, 2),
    ("R", 1233, 1, 3),
    ("R", 1234, 1, 9),
    ("R", 1235, 1, 4),
    ("R", 1237, 1, 18),
    ("R", 1238, 1, 1),
    ("R", 1242, 1, 8),
    ("R", 1243, 1, 3),
    ("R", 1251, 1, 13),
    ("R", 1261, 1, 1),
    ("R", 1262, 1, 22),
    ("R", 1263, 1, 22),
    # Procédure prud'hommes
    ("R", 1452, 1, 8),
    ("R", 1453, 1, 9),
    ("R", 1454, 1, 28),
    ("R", 1455, 1, 12),
    ("R", 1461, 1, 2),
    ("R", 1462, 1, 2),
    # CSE — aspects pratiques
    ("R", 2312, 1, 42),
    ("R", 2313, 1, 4),
    ("R", 2314, 1, 34),
    ("R", 2315, 1, 51),
    ("R", 2316, 1, 10),
    # Durée du travail — pratique
    ("R", 3121, 1, 35),
    ("R", 3131, 1, 5),
    ("R", 3132, 1, 5),
    ("R", 3141, 1, 34),
    ("R", 3142, 1, 48),
    # Salaire — pratique
    ("R", 3243, 1, 5),
    ("R", 3252, 1, 5),
    ("R", 3253, 1, 1),
    ("R", 3262, 1, 5),
    # Santé-sécurité — pratique
    ("R", 4121, 1, 4),
    ("R", 4131, 1, 4),
    ("R", 4141, 1, 20),
    ("R", 4151, 1, 2),
    ("R", 4152, 1, 17),
    ("R", 4153, 1, 52),
    ("R", 4228, 1, 37),
    ("R", 4323, 1, 107),
    ("R", 4412, 1, 160),
    ("R", 4511, 1, 12),
    ("R", 4512, 1, 16),
    # ── Partie D — Décrets simples ──
    ("D", 1232, 1, 11),
    ("D", 1233, 1, 48),
    ("D", 1237, 1, 6),
    ("D", 1242, 1, 8),
    ("D", 1251, 1, 6),
    ("D", 3141, 1, 34),
    ("D", 3171, 1, 18),
    ("D", 3243, 1, 8),
    ("D", 3253, 1, 9),
    ("D", 4121, 1, 1),
    ("D", 4152, 1, 11),
    ("D", 5134, 1, 73),
    ("D", 6323, 1, 12),
]


def _build_whitelist() -> frozenset[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for prefix, base, first, last in _RANGES:
        for tup in _gen(prefix, base, first, last):
            out.add(tup)
    # Articles sans suffixe (ex: L.1111 qu'on voit parfois dans les questions
    # mal formées). On les accepte aussi pour éviter un refus trop strict.
    bases_with_no_suffix: set[tuple[str, str]] = {
        (prefix, f"{prefix}{base}") for prefix, base, _, _ in _RANGES
    }
    out.update(bases_with_no_suffix)
    return frozenset(out)


_WHITELIST_CT: frozenset[tuple[str, str]] = _build_whitelist()


def is_whitelisted(prefix: str, canonical: str) -> bool:
    """Retourne True si `(prefix, canonical)` est dans la whitelist CT.

    Temps d'exécution : O(1) — lookup dans un frozenset.
    """
    return (prefix, canonical) in _WHITELIST_CT


def whitelist_size() -> int:
    """Taille effective de la whitelist (utilitaire pour logs/rapport)."""
    return len(_WHITELIST_CT)


__all__ = ["is_whitelisted", "whitelist_size"]
