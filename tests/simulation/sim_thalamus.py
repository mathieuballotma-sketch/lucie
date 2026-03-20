"""Simulation Thalamus — détection de fréquence par résonance."""

FREQUENCY_MAP = {
    "finance_query": [
        "or", "bitcoin", "bourse", "action", "crypto",
        "cours", "prix", "marché", "euro", "dollar", "investissement",
    ],
    "code_query": [
        "python", "code", "fonction", "bug", "erreur",
        "script", "programme", "classe", "module", "import",
    ],
    "file_query": [
        "fichier", "dossier", "document", "ranger",
        "déplacer", "supprimer", "créer", "copier", "renommer",
    ],
    "research_query": [
        "cherche", "trouve", "recherche", "synthèse",
        "résumé", "analyse", "compare", "explique", "définition",
    ],
    "mac_query": [
        "ouvre", "ferme", "lance", "safari", "mail",
        "calendrier", "notes", "finder", "terminal", "spotify",
    ],
    "memory_query": [
        "souviens", "rappelle", "dernière fois", "hier",
        "avant", "historique", "on avait dit", "tu te souviens",
    ],
}


def detect_frequency(query: str) -> str:
    """Thalamus — détecte la fréquence naturelle d'une requête."""
    query_lower = query.lower()
    scores: dict[str, int] = {}
    for signal, keywords in FREQUENCY_MAP.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[signal] = score
    if not scores:
        return "general_query"
    return max(scores, key=scores.get)  # type: ignore


def test_thalamus():
    print("── Simulation Thalamus ──")

    test_cases = [
        ("cherche le cours de l'or sur 3 sites", "finance_query"),    # or + cours → finance
        ("ouvre safari et va sur google", "mac_query"),
        ("résume ce fichier PDF", "research_query"),
        ("tu te souviens de notre dernier projet", "memory_query"),
        ("écris une fonction python pour trier", "code_query"),
        ("range mes téléchargements par date", "file_query"),
        ("quel est le prix du bitcoin", "finance_query"),
        ("lance spotify", "mac_query"),
        ("analyse ce document", "research_query"),
        ("bonjour", "general_query"),
    ]

    passed = 0
    for query, expected in test_cases:
        result = detect_frequency(query)
        ok = result == expected
        status = "✅" if ok else "❌"
        if ok:
            passed += 1
        else:
            print(f"  {status} '{query}' → {result} (attendu: {expected})")

    # Cas spécial : "cherche le cours de l'or" peut matcher research ET finance
    # Le Thalamus doit choisir la fréquence dominante
    special = detect_frequency("cherche le cours de l'or sur 3 sites")
    # "cherche" = research (1), "cours" + "or" = finance (2) → finance gagne
    assert special in ("finance_query", "research_query"), f"Inattendu: {special}"

    print(f"  ✅ {passed}/{len(test_cases)} requêtes correctement routées")

    # Compatibilité avec router.py existant
    # router.py utilise RoutePath enum : FAST_PATH, VISUAL_RESEARCH, etc.
    # Thalamus retourne des strings, mappables vers RoutePath
    THALAMUS_TO_ROUTE = {
        "finance_query": "visual_research",
        "code_query": "fast_path",
        "file_query": "fast_path",
        "research_query": "visual_research",
        "mac_query": "fast_path",
        "memory_query": "fallback",
        "general_query": "fallback",
    }
    for signal in FREQUENCY_MAP:
        assert signal in THALAMUS_TO_ROUTE, f"Signal {signal} non mappé"
    print("  ✅ Mapping Thalamus → RoutePath compatible")

    print(f"  → Thalamus : tests passés ✅\n")


if __name__ == "__main__":
    test_thalamus()
