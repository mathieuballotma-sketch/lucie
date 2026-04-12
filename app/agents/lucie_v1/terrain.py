"""
TerrainMixin — 3 couches d'apprentissage terrain pour les agents V1 Lucie.

  Couche 1 — Réactive     : comportement principal (handle, dans chaque agent)
  Couche 2 — Capitalisante: journalisation JSONL (patterns appris)
  Couche 3 — Générative   : proposition auto quand le seuil est atteint
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List


class TerrainMixin:
    """
    Injecte les couches capitalisante et générative dans chaque agent V1.

    Usage : class MonAgent(TerrainMixin, BaseAgent): ...
    Les sous-classes surchargent GENERATIVE_THRESHOLD et _build_generative_proposal().
    """

    JOURNAL_DIR = Path("data/journals/lucie_v1")
    GENERATIVE_THRESHOLD: int = 20  # nombre d'entrées avant déclenchement génératif

    def _log_to_journal(self, entry: Dict[str, Any]) -> None:
        """
        Couche capitalisante : écrit une entrée dans le journal JSONL de cet agent.
        Jamais bloquant — toutes les erreurs sont avalées silencieusement.
        """
        try:
            self.JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
            journal_path = self.JOURNAL_DIR / f"journal_{self.name}.jsonl"
            with open(journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), **entry}, ensure_ascii=False) + "\n")
            self._check_generative_threshold(journal_path)
        except Exception:
            pass

    def _check_generative_threshold(self, journal_path: Path) -> None:
        """
        Couche générative : si le nombre d'entrées dépasse GENERATIVE_THRESHOLD,
        construit une proposition et la publie sur l'EventBus.
        Rotate le journal après déclenchement pour remettre le compteur à zéro.
        """
        try:
            lines = journal_path.read_text(encoding="utf-8").splitlines()
            if len(lines) < self.GENERATIVE_THRESHOLD:
                return

            proposal = self._build_generative_proposal(lines)
            if not proposal:
                return

            # Publication EventBus (best-effort)
            event_bus = getattr(self, "event_bus", None)
            token = getattr(self, "token", None)
            if event_bus and token:
                try:
                    asyncio.create_task(
                        event_bus.publish(
                            channel="agent.generative_proposal",
                            data={"agent": self.name, "proposal": proposal},
                            source=self.name,
                            token=token,
                        )
                    )
                except RuntimeError:
                    pass  # Pas de boucle asyncio active — on ignore

            # Rotation : archive le journal pour remettre le compteur à zéro
            backup = journal_path.with_suffix(f".{int(time.time())}.jsonl.bak")
            journal_path.rename(backup)
        except Exception:
            pass

    def _build_generative_proposal(self, lines: List[str]) -> str:
        """
        Construit la proposition générative à partir des entrées du journal.
        À surcharger dans chaque agent pour un comportement contextuel.
        Retourne "" pour ne pas déclencher.
        """
        return ""
