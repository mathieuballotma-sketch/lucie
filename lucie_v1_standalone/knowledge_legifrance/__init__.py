"""
Intégration Légifrance live pour Lucie.

Source : dump officiel DILA LEGI (https://echanges.dila.gouv.fr/OPENDATA/LEGI/).
Licence données : Licence Ouverte Etalab.

Architecture :
- downloader  : récupère les tarballs DILA (full + incrémentaux)
- parser      : extrait les articles XML vers SQLite (parseur stdlib minimal)
- indexer     : matérialise le mapping thème → articles (6 éditions)
- retriever   : API publique pour les agents Lucie (LegifranceRetriever.search)
- sync        : orchestrateur download → parse → index → audit
- diff        : human-readable diff entre deux syncs

Le package `vendor/legi/` contient legi.py (CC0, commit 64c2c49) comme
référence / parseur optionnel pour traitements avancés. Le chemin par défaut
de Lucie utilise le parseur stdlib minimal pour maîtriser la dette technique
et la compat Python 3.13.
"""

from .retriever import LegifranceRetriever, LegalArticle

__all__ = ["LegifranceRetriever", "LegalArticle"]
