"""Pinning déterministe global des paramètres Ollama — Sprint 6 P2c-2.

POURQUOI ce module existe (vs. patcher chaque agent dans `config.py`) :

Selon `docs/architecture.md` (Beaume comme système expert formel),
`output(X) = constante` n'est garanti pour un appel LLM que si la
température est forcée à 0 ET un seed fixe est passé à Ollama. Sans cela,
deux exécutions consécutives sur la même question + mêmes sources peuvent
diverger — bruit qui contamine la mesure de la batterie 50q et confond
signal P2c-1 (prompt enrichi) avec variance LLM.

Centraliser le pinning AU NIVEAU DU TRANSPORT (ollama_client + ollama_provider)
plutôt qu'au niveau de chaque agent (LECTEUR_PARAMS, REDACTEUR_PARAMS, …)
garantit que :
  - aucun nouvel agent ne peut "oublier" le pinning par omission de config
  - la propriété "tout appel LLM est déterministe" est grep-able en une
    seule ligne (référence à `apply_deterministic_options`)
  - le flag `BEAUME_LLM_DETERMINISTIC=0` redonne en bloc la main aux PARAMS
    de chaque agent (notamment REDACTEUR_PARAMS["temperature"]=0.3) pour
    restaurer la variabilité native en prod si besoin.

Le flag est ON par défaut : la prod et la batterie partagent la même
politique de reproductibilité. C'est volontaire pour un assistant juridique
(auditabilité : même question → même réponse). Si dégradation littéraire
constatée, override explicite `BEAUME_LLM_DETERMINISTIC=0` au runtime.
"""

from __future__ import annotations

import os

# Seed arbitraire mais STABLE inter-runs. Référence Douglas Adams (« 42 ») :
# n'importe quel entier conviendrait, ce qui compte est la constance.
# Documenté ici pour satisfaire la règle Beaume "pas de magic numbers" et
# permettre l'override en tests sans dépendre du flag d'environnement.
_DETERMINISTIC_SEED: int = 42

_FLAG_NAME: str = "BEAUME_LLM_DETERMINISTIC"
_DEFAULT_ENABLED: str = "1"


def is_deterministic_enabled() -> bool:
    """Indique si le pinning déterministe est actif (lecture du flag env).

    Exposée pour les tests et le diagnostic ; le pipeline ne devrait pas avoir
    besoin de la consulter — `apply_deterministic_options` est suffisante.
    """
    return os.environ.get(_FLAG_NAME, _DEFAULT_ENABLED) == "1"


def apply_deterministic_options(options: dict | None) -> dict:
    """Renvoie un dict d'options Ollama avec `temperature=0` et `seed=42` forcés
    si le flag `BEAUME_LLM_DETERMINISTIC` est actif (défaut "1").

    Préserve toutes les autres clés de `options` (num_ctx, num_predict, top_p,
    stop, …). Renvoie une COPIE — ne mute jamais l'argument, sécurité contre
    des effets de bord sur les `*_PARAMS` partagés au niveau module.

    Quand le flag vaut "0" : renvoie une copie inchangée de `options` (ou
    `{}` si `options is None`). Le comportement reste donc compatible avec
    l'ancien code (`if options: payload["options"] = options`).
    """
    pinned: dict = dict(options or {})
    if is_deterministic_enabled():
        pinned["temperature"] = 0
        pinned["seed"] = _DETERMINISTIC_SEED
    return pinned
