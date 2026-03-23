"""
Mode furtif - Minimise les traces laissées par l'agent.
"""

import os
import sys
from typing import Optional, TextIO

from app.utils.logger import logger


class StealthMode:
    """
    Gère les opérations furtives (désactivation des logs, etc.).
    Note: Ce module est expérimental et peut ne pas fonctionner sur tous les systèmes.
    """

    def __init__(self, config: dict[str, object]) -> None:
        self.config = config
        self.original_stdout: Optional[TextIO] = None
        self.original_stderr: Optional[TextIO] = None

    def enable(self) -> None:
        """Active le mode furtif (redirige stdout/stderr vers /dev/null)."""
        if not self.config.get("stealth_enabled", False):
            return

        logger.warning("⚠️ Mode furtif activé - les logs ne seront plus visibles dans le terminal")

        # Sauvegarder les descripteurs originaux
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr

        # Rediriger vers /dev/null
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')

        # Désactiver le logger
        import logging
        logging.disable(logging.CRITICAL)

    def disable(self) -> None:
        """Désactive le mode furtif."""
        if self.original_stdout:
            sys.stdout.close()
            sys.stdout = self.original_stdout
        if self.original_stderr:
            sys.stderr.close()
            sys.stderr = self.original_stderr

        import logging
        logging.disable(logging.NOTSET)

        logger.info("Mode furtif désactivé")
