"""
PatternSanitizer — Filtre PII avant injection dans AbstractMemory.

Principe : toute observation qui arrive de PersonalMemory passe par ici
avant d'atterrir dans AbstractMemory. Le résultat ne contient aucune
information personnelle identifiable — uniquement la structure abstraite
du pattern.

Ce module est le futur point d'injection de la couche de sanitisation P2P :
quand le maillage P2P sera implémenté, seule cette couche sera modifiée.
AbstractMemory n'a jamais accès aux données brutes.

PII détecté et supprimé :
- Noms propres (heuristique : mot commençant par majuscule précédé de M./Mme/Mme.)
- Numéros de dossier (patterns : AAAA-NNN, NNN-AAAA, dossier n°…)
- Montants monétaires (patterns : X €, X euros, X,XXX €)
- Dates précises (JJ/MM/AAAA, AAAA-MM-JJ)
- Numéros de téléphone, SIRET, NIR (sécu)
- Adresses email

Aucun LLM appelé ici — règles déterministes uniquement (zéro latence).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns PII
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    # Noms propres après civilité
    (re.compile(r"\b(M\.?|Mme\.?|Monsieur|Madame|Me\.?)\s+[A-ZÉÈÊËÀÂÙÛÎ][a-zéèêëàâùûî\-]+\b"), "[NOM]"),
    # Numéros de dossier (ex: 2024-001, 24-1234)
    (re.compile(r"\b\d{2,4}[-/]\d{3,6}\b"), "[DOSSIER]"),
    # Montants monétaires (ex: 45 000 €, 1 500,50 euros) — pas de \b final car € n'est pas \w
    (re.compile(r"\b\d[\d\s]*(?:,\d+)?\s*(?:€|euros?)", re.IGNORECASE), "[MONTANT]"),
    # Dates JJ/MM/AAAA ou AAAA-MM-JJ
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), "[DATE]"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "[DATE]"),
    # Emails
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    # Téléphones (FR)
    (re.compile(r"\b(?:0|\+33\s?)[1-9](?:[\s.\-]?\d{2}){4}\b"), "[TEL]"),
    # SIRET / SIREN
    (re.compile(r"\b\d{9}(?:\d{5})?\b"), "[SIRET]"),
    # NIR sécurité sociale (13 chiffres + clé)
    (re.compile(r"\b[12]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\b"), "[NIR]"),
]


def sanitize(text: str) -> str:
    """
    Retire les PII d'un texte et retourne le pattern abstrait.

    Exemple :
        "Monsieur Dupont, dossier 2024-001, 45 000 €"
        → "NOM, dossier [DOSSIER], [MONTANT]"

    Args:
        text: Texte brut potentiellement contenant des PII.

    Returns:
        Texte nettoyé, anonymisé, sans PII.
    """
    result = text
    for pattern, replacement in _PII_PATTERNS:
        result = pattern.sub(replacement, result)
    return result.strip()


def extract_domain_signal(text: str) -> str:
    """
    Extrait le domaine de droit social le plus probable depuis le texte.

    Utilisé pour créer un pattern abstrait domaine → signal dans AbstractMemory.
    Retourne le domaine détecté ou "general" si aucun signal fort.
    """
    text_lower = text.lower()
    # Mapping mots-clés → domaine
    domains = [
        (["licenciement", "licencier", "rupture conventionnelle", "inaptitude"], "licenciement"),
        (["salaire", "rémunération", "brut", "net", "cotisation", "bulletin"], "rémunération"),
        (["congé", "arrêt maladie", "at", "accident du travail", "maternité"], "absences"),
        (["cdd", "cdi", "contrat", "embauche", "période d'essai"], "contrat"),
        (["prud'homme", "prudhommes", "tribunal", "contentieux", "procédure"], "contentieux"),
        (["disciplinaire", "faute", "mise à pied", "avertissement", "sanction"], "disciplinaire"),
        (["négociation", "accord collectif", "cse", "délégué", "syndicat", "nao"], "négociation"),
        (["classification", "ccn", "convention collective", "coefficient"], "classification"),
    ]
    for keywords, domain in domains:
        if any(kw in text_lower for kw in keywords):
            return domain
    return "general"
