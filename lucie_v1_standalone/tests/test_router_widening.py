"""
Tests — KI-001 fix : élargissement whitelist router + passthrough ambigu.

Vérifie que :
  - 10 requêtes CSE / préavis / PSE / articles L. passent en domaine licenciement éco
  - 5 requêtes hors-scope strictement refusées
  - 3 requêtes ambiguës passent au Retriever (intent='recherche_ambiguë', valid=True)
"""

from __future__ import annotations

import pytest

from lucie_v1_standalone.router import is_ambiguous_passthrough, route, validate


# ── 1. Requêtes CSE / préavis / PSE → domaine licenciement éco ───────────────

@pytest.mark.parametrize("query", [
    "Le CSE a-t-il été consulté avant ce licenciement ?",
    "Mon CSE n'a pas été informé — est-ce légal ?",
    "Quel est le délai de préavis pour un CDI de 3 ans ?",
    "Mon préavis a été réduit sans accord — que faire ?",
    "L'entreprise a-t-elle l'obligation de mettre en place un PSE ?",
    "Le PSE doit-il être validé par la DREETS ?",
    "Quels sont les critères d'ordre des licenciements dans un PSE ?",
    "La consultation obligatoire du CSE a-t-elle eu lieu ?",
    "L'article L.1233-30 impose quels délais de consultation ?",
    "Mon employeur a notifié le licenciement sans respecter l'ordre des licenciements.",
])
def test_cse_previs_pse_search(query: str) -> None:
    r = route(query)
    assert r["level"] == "search", f"Attendu search, obtenu {r['level']!r} pour : {query!r}"
    assert r["intent"] == "recherche_juridique"

    v = validate(query)
    assert v["valid"], f"Requête refusée à tort : {query!r}"


# ── 2. Requêtes hors-scope → toujours refusées ───────────────────────────────

@pytest.mark.parametrize("query", [
    "J'ai eu un accident de voiture hier soir.",
    "Quelle est la peine pour vol à l'étalage ?",
    "Comment déclarer mes revenus fonciers aux impôts ?",
    "Mon propriétaire refuse de rembourser ma caution.",
    "Quel médecin consulter pour une douleur au dos ?",
])
def test_out_of_scope_refused(query: str) -> None:
    v = validate(query)
    assert not v["valid"], f"Requête hors-scope non refusée : {query!r}"
    assert v["intent"] == "out_of_scope"
    assert v["refusal_reason"]


# ── 3. Requêtes ambiguës → passthrough Retriever ─────────────────────────────

@pytest.mark.parametrize("query", [
    "J'ai été licencié.",
    "Mon contrat de travail a été rompu.",
    "Quels sont mes droits ?",
])
def test_ambiguous_passthrough(query: str) -> None:
    r = route(query)
    assert r["level"] == "search", f"Attendu search pour ambigu, obtenu {r['level']!r} : {query!r}"
    assert r["intent"] == "recherche_ambiguë"

    v = validate(query)
    assert v["valid"], f"Requête ambiguë refusée alors qu'elle devrait passer : {query!r}"

    assert is_ambiguous_passthrough(query), f"is_ambiguous_passthrough False pour : {query!r}"
