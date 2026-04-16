"""
LegalPipeline — orchestrateur linéaire du pipeline V1 droit social.

Flux : Router → Lecteur → Retriever → Rédacteur → Vérificateur

Contourne le FrontalCortex — point d'entrée direct pour les requêtes avocat.
Appelé via LucidEngine.process_legal_query() (à ajouter dans engine.py).
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

from ...services.audit_trail import AuditTrail
from ...utils.logger import logger
from .lecteur import LecteurAgent
from .redacteur import RedacteurAgent
from .retriever import RetrieverAgent
from .router import LegalRouter
from .verificateur import VerificateurAgent

_PIPELINE_TIMEOUT = 600.0  # secondes


class LegalPipeline:
    """
    Orchestre les 5 rôles V1 de façon linéaire.
    Gère les erreurs à chaque étape et retourne toujours une réponse lisible.
    """

    def __init__(
        self,
        manager: Any,   # ProviderManager
        bus: Any,
        event_bus: Any = None,
    ):
        self.router = LegalRouter()
        self.lecteur = LecteurAgent(
            llm_service=manager, bus=bus, event_bus=event_bus
        )
        self.retriever = RetrieverAgent(
            llm_service=manager, bus=bus, event_bus=event_bus
        )
        self.redacteur = RedacteurAgent(
            llm_service=manager, bus=bus, event_bus=event_bus
        )
        self.verificateur = VerificateurAgent(
            llm_service=manager, bus=bus, event_bus=event_bus
        )
        audit_dir = Path("./data/audit")
        audit_dir.mkdir(parents=True, exist_ok=True)
        self.audit_trail = AuditTrail(db_path=audit_dir / "legal_pipeline.db")
        self._audit_started = False
        logger.info("⚖️  LegalPipeline V1 initialisé")

    def set_token(self, token: str) -> None:
        """Injecte le token EventBus dans tous les agents LLM."""
        for agent in (self.lecteur, self.retriever, self.redacteur, self.verificateur):
            agent.set_token(token)

    # ─── Point d'entrée public ────────────────────────────────────────────────

    async def run(
        self,
        query: str,
        document_text: Optional[str] = None,
        force: bool = False,
    ) -> str:
        """
        Exécute le pipeline complet avec timeout global.

        Args:
            query: Requête de l'avocat.
            document_text: Texte du document à analyser (optionnel).
            force: Bypass le filtrage du Router (pour les démos).

        Returns:
            Note finale validée en Markdown, ou message de refus/erreur.
        """
        start = time.time()
        logger.info(f"⚖️  Pipeline démarré — query={query[:80]}…")
        try:
            result = await asyncio.wait_for(
                self._run_pipeline(query, document_text, force),
                timeout=_PIPELINE_TIMEOUT,
            )
            elapsed = time.time() - start
            logger.info(f"⚖️  Pipeline terminé en {elapsed:.1f}s")
            return result
        except asyncio.TimeoutError:
            elapsed = time.time() - start
            logger.error(f"Pipeline timeout après {elapsed:.1f}s")
            return (
                f"**Erreur** : le pipeline a dépassé le timeout de "
                f"{_PIPELINE_TIMEOUT:.0f}s. "
                "Réessayez ou réduisez la taille du document."
            )
        except Exception as exc:
            logger.error(f"Pipeline erreur inattendue : {exc}")
            return f"**Erreur pipeline** : {exc}"

    # ─── Pipeline interne ─────────────────────────────────────────────────────

    async def _run_pipeline(
        self,
        query: str,
        document_text: Optional[str],
        force: bool,
    ) -> str:
        if not self._audit_started:
            await self.audit_trail.start()
            self._audit_started = True

        await self.audit_trail.record(
            "pipeline.start", user="system",
            data={"query": query[:200], "has_document": document_text is not None},
        )

        # ── Étape 1 : Router (< 10ms) ─────────────────────────────────────────
        routing = self.router.validate(query, document_text, force=force)
        await self.audit_trail.record(
            "pipeline.routing", user="system",
            data={"valid": routing["valid"], "reason": routing.get("refusal_reason", "")[:200]},
        )
        if not routing["valid"]:
            logger.info(f"Router : refus — {routing['refusal_reason'][:60]}…")
            return str(routing["refusal_reason"])

        doc = routing.get("document") or document_text or query
        logger.info("✅ Router : scope validé")

        # ── Étape 2 : Lecteur (~3-5s) ─────────────────────────────────────────
        logger.info("📄 Lecteur : extraction des faits…")
        faits_json = await self.lecteur.handle(doc)

        try:
            faits_data = json.loads(faits_json)
            if "erreur" in faits_data:
                return (
                    f"**Erreur Lecteur** : {faits_data['erreur']}\n\n"
                    "Le document fourni ne semble pas être une lettre "
                    "de licenciement économique."
                )
        except json.JSONDecodeError:
            pass  # JSON mal formé mais on continue

        logger.info("✅ Lecteur : faits extraits")
        await self.audit_trail.record("pipeline.lecteur", user="system", data={"ok": True})

        # ── Étape 3 : Retriever (~2-4s) ───────────────────────────────────────
        logger.info("🔍 Retriever : recherche dans la base curatée…")
        sources_json = await self.retriever.handle(faits_json)
        logger.info("✅ Retriever : sources récupérées")
        await self.audit_trail.record("pipeline.retriever", user="system", data={"ok": True})

        # ── Étape 4 : Rédacteur (~8-15s) ──────────────────────────────────────
        logger.info("✍️  Rédacteur : rédaction de la note…")
        note_markdown = await self.redacteur.handle(faits_json, sources_json)

        if note_markdown.startswith("**RÉDACTION IMPOSSIBLE**"):
            # Base curatée vide — retourner un rapport d'état lisible
            return (
                "# Note d'analyse — Licenciement économique\n\n"
                "> **Analyse partielle** — base curatée insuffisante.\n\n"
                "## Faits extraits\n\n"
                f"```json\n{faits_json}\n```\n\n"
                "## Sources disponibles\n\n"
                f"{note_markdown}\n\n"
                "_Note générée par Lucie V1 — à vérifier par un avocat qualifié._"
            )

        logger.info("✅ Rédacteur : note rédigée")
        await self.audit_trail.record("pipeline.redacteur", user="system", data={"ok": True})

        # ── Étape 5 : Vérificateur (~2-3s) ────────────────────────────────────
        logger.info("🔎 Vérificateur : contrôle des citations…")
        verification_json = await self.verificateur.handle(note_markdown, sources_json)

        try:
            verification = json.loads(verification_json)
            note_finale = verification.get("note_corrigee", note_markdown)
            score = verification.get("score_fiabilite", 1.0)
            verdict = verification.get("verdict", "INCONNU")
        except json.JSONDecodeError:
            note_finale = note_markdown
            score = 0.0
            verdict = "ERREUR VÉRIFICATION"

        logger.info(f"✅ Vérificateur : {verdict} (score={score:.2f})")
        await self.audit_trail.record(
            "pipeline.verificateur", user="system",
            data={"verdict": verdict, "score": score},
        )

        # ── Réponse finale ────────────────────────────────────────────────────
        disclaimer = (
            "\n\n---\n"
            f"_Note générée par Lucie V1 — "
            f"Score de fiabilité : {score:.0%} — Verdict : {verdict}_\n"
            "_À vérifier par un avocat qualifié avant tout usage professionnel._"
        )
        return note_finale + disclaimer
