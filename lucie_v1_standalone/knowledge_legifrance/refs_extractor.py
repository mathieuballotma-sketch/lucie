"""refs_extractor — extension de extract_legal_refs() pour le pipeline KB compact.

Sprint K-1 : capture en plus du parser de retriever.py les formes contextuelles
"voir L.1234-5", "selon l'article R.4121-3", "cf. art. L.1132-1", utiles pour
construire un graphe DAG des renvois inter-articles.

Pourquoi un module séparé plutôt que modifier retriever.py :
- Invariant K-1 : ne pas modifier le retriever client en production.
- Le retriever client extrait des refs **depuis la query utilisateur** (peu de
  bruit attendu). Le graphe extrait depuis le **texte d'articles juridiques**
  (contexte plus riche, formes "voir", "selon", "cf." abondantes).
"""

from __future__ import annotations

import re
from typing import Iterator

from lucie_v1_standalone.knowledge_legifrance.retriever import _LEGAL_REF_RE

_CONTEXT_PREFIX_RE = re.compile(
    r"""(?xi)
    (?:
        voir(?:\s+(?:également|aussi))?       # 'voir', 'voir également', 'voir aussi'
      | selon(?:\s+l[''])?(?:\s+article)?    # 'selon', "selon l'article"
      | cf\.?                                  # 'cf', 'cf.'
      | conformément\s+à(?:\s+l[''])?(?:\s+article)?
      | par\s+application\s+(?:de\s+)?(?:l['']\s*)?(?:article|art\.?)
      | mentionné[es]?\s+(?:à\s+l['']\s*)?(?:article|art\.?)
      | prévu[es]?\s+(?:à\s+l['']\s*|par\s+l['']\s*)?(?:article|art\.?)
      | en\s+application\s+(?:de\s+)?(?:l['']\s*)?(?:article|art\.?)
    )
    \s*
    """
)

_INLINE_REF_TAIL_RE = re.compile(
    r"""(?xi)
    (?:l['']?\s*)?                              # apostrophe possible
    (?:article|art\.?)?\s*                     # 'article' / 'art.' optionnel
    (?P<prefix>[LRDA])\s*\.?\s*                # préfixe L/R/D/A OBLIGATOIRE ici
    (?P<numeric>\d{1,5})                        # numéro principal
    (?:\s*-\s*(?P<suffix>\d{1,4}))?            # suffixe -N optionnel
    """
)


def _iter_context_refs(text: str) -> Iterator[tuple[str, str]]:
    """Yield (prefix, num) pour chaque renvoi détecté via un déclencheur contextuel.

    Un déclencheur "voir/selon/cf./conformément/..." doit précéder immédiatement
    une référence au format L.NNNN-N. On exige le préfixe L/R/D/A pour éviter
    les faux positifs ("voir 1234" sans préfixe = bruit).
    """
    for trigger in _CONTEXT_PREFIX_RE.finditer(text):
        tail = text[trigger.end(): trigger.end() + 60]
        m = _INLINE_REF_TAIL_RE.match(tail)
        if m is None:
            continue
        prefix = (m.group("prefix") or "").upper()
        numeric = m.group("numeric") or ""
        suffix = m.group("suffix")
        if not numeric:
            continue
        num = numeric + (f"-{suffix}" if suffix else "")
        yield (prefix, num)


def extract_refs_extended(text: str) -> list[tuple[str, str]]:
    """Extraction étendue des renvois (base retriever + déclencheurs contextuels).

    Returns:
        Liste dédupliquée de tuples (prefix, num_canonique). Préserve l'ordre
        de première occurrence pour permettre des heuristiques d'ordering.

    Garde-fous (règle qualité #3) :
        - Texte vide → []
        - Texte non-str → raise TypeError (pas d'avalement silencieux)
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    if not text:
        return []

    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for match in _LEGAL_REF_RE.finditer(text):
        prefix = (match.group("prefix") or "").upper()
        numeric = match.group("numeric") or ""
        suffix = match.group("suffix")
        if not numeric:
            continue
        if not prefix and not suffix:
            continue
        num = numeric + (f"-{suffix}" if suffix else "")
        key = (prefix, num)
        if key in seen:
            continue
        seen.add(key)
        refs.append(key)

    for key in _iter_context_refs(text):
        if key in seen:
            continue
        seen.add(key)
        refs.append(key)

    return refs


def extract_refs_from_behavior(expected_behavior: str) -> list[tuple[str, str]]:
    """Extrait expected_articles depuis le champ 'expected_behavior' du bench.

    Le bench swiss_watch_50.json ne contient pas de champ expected_articles
    explicite ; on les reconstitue depuis expected_behavior par regex. Choix
    acté par Mathieu (2026-05-15).

    Returns:
        Liste de refs (prefix, num) attendues. Vide si la question n'attend pas
        d'article particulier (ex out-of-scope, article invalide).
    """
    return extract_refs_extended(expected_behavior)
