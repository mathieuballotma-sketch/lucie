"""
lucie_v1 — Pipeline V1 droit social (licenciement économique).

Namespace isolé : n'interagit pas avec les agents existants.
Point d'entrée : LegalPipeline.run(query, document_text)

Usage via LucidEngine :
    result = await engine.process_legal_query(query, document_text)

Usage direct :
    from app.agents.lucie_v1 import LegalPipeline
    pipeline = LegalPipeline(manager=..., bus=..., event_bus=...)
    note = await pipeline.run("analyser cette lettre", document_text=lettre)
"""

from .pipeline import LegalPipeline
from .router import LegalRouter, SCOPE_KEYWORDS
from .lecteur import LecteurAgent
from .retriever import RetrieverAgent
from .redacteur import RedacteurAgent
from .verificateur import VerificateurAgent
from .terrain import TerrainMixin

__all__ = [
    "LegalPipeline",
    "LegalRouter",
    "SCOPE_KEYWORDS",
    "LecteurAgent",
    "RetrieverAgent",
    "RedacteurAgent",
    "VerificateurAgent",
    "TerrainMixin",
]
