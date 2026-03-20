import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "agent_lucide",
    level: int = logging.DEBUG,
    log_file: Optional[Path] = None,  # FIX : Optional[Path] au lieu de Path = None
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure et retourne un logger avec sortie console et fichier optionnel."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file is not None:  # FIX : guard explicite
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_path), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


logger = setup_logger()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Retourne un logger avec un nom spécifique."""
    if name:
        return logging.getLogger(f"agent_lucide.{name}")
    return logger
