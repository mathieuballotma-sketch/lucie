"""
MemoryStore — Façade unique pour toute la couche mémoire de Lucie.

Architecture à deux couches :

  ┌──────────────────────────────────────────────────────────────┐
  │  PersonalMemory  (données brutes — locale pour toujours)     │
  │  → observe() reçoit la requête brute + contexte pipeline     │
  │  → recall() retourne les nœuds pertinents                   │
  │  → snapshot() retourne le profil utilisateur complet         │
  └───────────────────────┬──────────────────────────────────────┘
                          │ sanitizer.sanitize() + extract_domain_signal()
                          ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  AbstractMemory  (patterns anonymisés — futur P2P)           │
  │  → accumulate() reçoit le texte nettoyé                      │
  │  → patterns_above_threshold() → ProactiveEngine (Bloc 2)     │
  │  → export_for_p2p() → couche réseau P2P (Bloc N+2)          │
  └──────────────────────────────────────────────────────────────┘

Règle d'accès :
  PersonalMemory → sanitizer → AbstractMemory   ✅
  AbstractMemory → PersonalMemory               ❌ jamais

Le ProactiveEngine (Bloc 2) ne lira QUE AbstractMemory — il ne connaît
pas l'existence de PersonalMemory.

Usage :
    store = MemoryStore("data/")
    await store.initialize()
    await store.observe({"query": "licenciement économique", "domain": "licenciement"})
    results = await store.recall("licenciement")
    patterns = store.abstract_patterns_above_threshold()
    profile = await store.snapshot()
    await store.close()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .abstract import AbstractMemory, AbstractPattern, SIGNAL_ACTIVATION_THRESHOLD
from .personal import PersonalMemory
from .sanitizer import extract_domain_signal, sanitize

logger = logging.getLogger(__name__)


class MemoryStore:
    """
    Point d'entrée unique pour la mémoire adaptative de Lucie.

    Orchestre PersonalMemory et AbstractMemory en s'assurant que
    les données brutes ne traversent jamais la frontière vers AbstractMemory.
    """

    def __init__(self, data_dir: str = "data/memory") -> None:
        base = Path(data_dir)
        self._personal = PersonalMemory(str(base / "personal.db"))
        self._abstract = AbstractMemory(str(base / "abstract.db"))

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Ouvre les deux couches de stockage."""
        await self._personal.initialize()
        self._abstract.initialize()

    async def close(self) -> None:
        """Ferme proprement les deux couches."""
        await self._personal.close()
        self._abstract.close()

    async def __aenter__(self) -> "MemoryStore":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Interface publique — couche pipeline
    # ------------------------------------------------------------------

    async def observe(self, context: dict) -> None:
        """
        Enregistre une observation depuis le pipeline.

        Flux :
        1. Écrit le contenu brut dans PersonalMemory.
        2. Sanitise le contenu (PII → placeholders).
        3. Accumule le pattern anonymisé dans AbstractMemory.

        Args:
            context: Dict avec "query"/"content"/"text", optionnellement
                     "domain", "source", "node_type".
        """
        # 1 — Couche personnelle (données brutes)
        await self._personal.observe(context)

        # 2 — Sanitisation avant AbstractMemory
        raw_content = (
            context.get("query")
            or context.get("content")
            or context.get("text")
            or ""
        )
        if not raw_content:
            return

        clean = sanitize(str(raw_content))
        domain = context.get("domain") or extract_domain_signal(str(raw_content))

        # 3 — Couche abstraite (patterns anonymisés uniquement)
        self._abstract.accumulate(domain, clean)

    async def recall(self, query: str, top_k: int = 5) -> List[dict]:
        """
        Rappel depuis PersonalMemory — retourne les nœuds pertinents.

        Args:
            query: Texte de recherche.
            top_k: Nombre max de résultats.

        Returns:
            Liste de dicts avec content, confidence, node_type, source.
        """
        return await self._personal.recall(query, top_k=top_k)

    async def decay(self, time_elapsed: float = 0.0) -> dict:
        """
        Applique le déclin LTD sur les deux couches.

        Returns:
            Dict {"personal_archived": int, "abstract_decayed": bool}.
        """
        personal_archived = await self._personal.decay(time_elapsed)
        self._abstract.apply_decay()
        return {"personal_archived": personal_archived, "abstract_decayed": True}

    async def reset(self) -> dict:
        """Efface toute la mémoire (personal + abstract).

        Action irréversible — la double confirmation utilisateur (saisie du
        mot-clé « EFFACER ») doit être imposée côté HUD avant l'appel.
        Swiss watch — règle 6 (transparence radicale + sortie facile).

        Returns:
            Dict {"personal_deleted": int, "abstract_deleted": int}.
        """
        personal_deleted = await self._personal.reset_all()
        abstract_deleted = self._abstract.clear()
        return {
            "personal_deleted": personal_deleted,
            "abstract_deleted": abstract_deleted,
        }

    async def snapshot(self) -> dict:
        """
        Profil complet de l'utilisateur.

        Contient :
        - Le profil PersonalMemory (nœuds par type, datés et sourcés)
        - Le signal AbstractMemory par domaine (agrégé)

        Returns:
            Dict structuré pour "Ma fiche Lucie" dans l'onboarding.
        """
        personal_profile = await self._personal.snapshot()
        domain_signals = self._abstract.signal_by_domain()
        return {
            "personal": personal_profile,
            "domain_signals": domain_signals,
        }

    # ------------------------------------------------------------------
    # Interface publique — couche AbstractMemory (Bloc 2)
    # ------------------------------------------------------------------

    def abstract_patterns_above_threshold(
        self,
        threshold: float = SIGNAL_ACTIVATION_THRESHOLD,
        domain: Optional[str] = None,
    ) -> List[AbstractPattern]:
        """
        Patterns abstraits dont le signal dépasse le seuil d'activation.

        Bloc 2 (ProactiveEngine) lira cette méthode pour déclencher des
        propositions proactives. Elle ne retourne aucune donnée personnelle.
        """
        return self._abstract.patterns_above_threshold(threshold=threshold, domain=domain)

    def abstract_signal_by_domain(self) -> Dict[str, float]:
        """Signal agrégé par domaine — diagnostic de spécialisation."""
        return self._abstract.signal_by_domain()

    def export_for_p2p(self) -> List[dict]:
        """
        Export P2P — uniquement les patterns anonymisés au-dessus du seuil.

        Future interface du maillage P2P (Bloc N+2). Ne contient aucun
        identifiant personnel, aucune donnée brute.
        """
        return self._abstract.export_for_p2p()

    # ------------------------------------------------------------------
    # Interface publique — accès direct PersonalMemory (usage interne)
    # ------------------------------------------------------------------

    async def get_context_for(self, task_description: str, top_k: int = 5) -> str:
        """Contexte formaté pour enrichir un prompt agent."""
        return await self._personal.get_context_for(task_description, top_k=top_k)
