"""
Configuration logging root pour Beaume.

`setup_logging()` installe deux handlers sur le logger root :
  - StreamHandler(stderr) — visible dans le terminal live
  - RotatingFileHandler → ~/Library/Logs/Beaume/beaume.log (10 MB × 5)

Niveau par défaut : INFO. Override via `BEAUME_LOG_LEVEL=DEBUG`
(ancien `LUCIE_LOG_LEVEL` accepté en alias deprecated).
Bypass complet si `BEAUME_QUIET=1` (ou `LUCIE_QUIET=1` deprecated).

À appeler AU TOUT DÉBUT de `app/ui/hud_native.py` (avant les imports
de `lucie_v1_standalone.*` qui instancient leurs loggers), pour que
les `logger.info(...)` du pipeline, du classifier, du retriever, etc.
soient visibles.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from lucie_v1_standalone.config import env_legacy

_LOG_DIR = Path.home() / "Library" / "Logs" / "Beaume"
_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_SENTINEL = "_lucie_root_configured"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5


def setup_logging() -> None:
    """Configure le ROOT logger. Idempotent. No-op si BEAUME_QUIET=1."""
    if env_legacy("QUIET") == "1":
        return
    root = logging.getLogger()
    if getattr(root, _SENTINEL, False):
        return

    level = (env_legacy("LOG_LEVEL", "INFO") or "INFO").upper()
    root.setLevel(level)
    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_h = RotatingFileHandler(
        _LOG_DIR / "beaume.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_h.setFormatter(fmt)
    root.addHandler(file_h)

    stream_h = logging.StreamHandler(sys.stderr)
    stream_h.setFormatter(fmt)
    root.addHandler(stream_h)

    setattr(root, _SENTINEL, True)
