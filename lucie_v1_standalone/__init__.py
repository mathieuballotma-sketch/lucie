"""
Lucie V1 Standalone — pipeline juridique droit social.

Module autonome, aucune dépendance au reste du repo.
Seules dépendances externes : httpx, asyncio, json, pathlib, re, math, collections.

Usage :
    python -m lucie_v1_standalone "Ma question juridique" --document "Texte du doc"
    python -m lucie_v1_standalone --help
"""

from .pipeline import run
from .router import SCOPE_KEYWORDS, validate as router_validate

__all__ = ["run", "router_validate", "SCOPE_KEYWORDS"]
