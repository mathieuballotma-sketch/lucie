"""
SmallTalkHandler — Dictionnaire de patterns → réponses canoniques.

30+ patterns couvrant : salutations, remerciements, identité, fonctions,
déclinaisons (météo, blague), clôtures. 0 LLM — réponses statiques.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# Chaque entrée : (pattern_re, réponse canonique)
# Ordre important : les patterns les plus spécifiques d'abord.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ── Identité ─────────────────────────────────────────────────────────────
    (re.compile(r'\b(qui es.tu|comment tu t\'appelles|c\'est quoi ton nom|quel est ton nom)\b', re.I | re.U),
     "Je suis Beaume, assistant juridique spécialisé en licenciement économique."),

    (re.compile(r'\b(tu es (un |une )?(quoi|qui)|qu\'est.ce que tu es)\b', re.I | re.U),
     "Je suis Beaume, un assistant juridique dédié au droit du licenciement économique."),

    # ── Fonctions ─────────────────────────────────────────────────────────────
    (re.compile(r'\b(tu peux faire quoi|quelles sont tes fonctions|qu\'est.ce que tu (fais|peux)|tes capacités|tu es capable de quoi)\b', re.I | re.U),
     "Je réponds aux questions sur le licenciement économique : procédure, indemnités, "
     "reclassement, contestation, rédaction de courriers. Je ne traite pas d'autres domaines juridiques."),

    # ── Aide générale ─────────────────────────────────────────────────────────
    (re.compile(r'^(aide.moi|help|aide|j\'ai besoin d\'aide)[\s!.,?]*$', re.I | re.U),
     "Bonjour. Posez-moi votre question sur le licenciement économique — "
     "procédure, délais, indemnités, recours — je ferai de mon mieux pour vous aider."),

    # ── Salutations ───────────────────────────────────────────────────────────
    (re.compile(r'^(bonjour|bonsoir)[\s!.,?]*$', re.I | re.U),
     "Bonjour. Comment puis-je vous aider sur le licenciement économique ?"),

    (re.compile(r'^(salut|hello|hi|hey|coucou|yo)[\s!.,?]*$', re.I | re.U),
     "Bonjour. Quelle est votre question sur le licenciement économique ?"),

    (re.compile(r'^(bonne journée|bonne matinée)[\s!.,?]*$', re.I | re.U),
     "Bonne journée à vous. N'hésitez pas à revenir si vous avez une question."),

    (re.compile(r'^(bonne soirée|bonne nuit)[\s!.,?]*$', re.I | re.U),
     "Bonne soirée. Je reste disponible si besoin."),

    # ── Comment ça va ─────────────────────────────────────────────────────────
    (re.compile(r'\b(comment ça va|comment vas.tu|ça va)\b', re.I | re.U),
     "Très bien, merci. Et vous ? Avez-vous une question sur le licenciement économique ?"),

    # ── Remerciements ─────────────────────────────────────────────────────────
    (re.compile(r'^(merci|thank you|thanks|merci beaucoup|merci bien)[\s!.,?]*$', re.I | re.U),
     "Je vous en prie. N'hésitez pas si vous avez d'autres questions."),

    (re.compile(r'\b(merci pour|merci de|merci d\'avoir)\b', re.I | re.U),
     "Avec plaisir. Avez-vous d'autres questions sur votre situation ?"),

    # ── Accord / validation ───────────────────────────────────────────────────
    (re.compile(r'^(ok|okay|d\'accord|entendu|compris|parfait|super|très bien|nickel)[\s!.,?]*$', re.I | re.U),
     "Très bien. Y a-t-il autre chose dont vous avez besoin ?"),

    (re.compile(r'^(oui|yes|ouais|yep)[\s!.,?]*$', re.I | re.U),
     "D'accord. Pouvez-vous me donner plus de détails sur votre situation ?"),

    (re.compile(r'^(non|no|nope|pas vraiment)[\s!.,?]*$', re.I | re.U),
     "Très bien. Faites-moi signe si vous avez besoin d'aide."),

    # ── Clôtures ──────────────────────────────────────────────────────────────
    (re.compile(r'^(au revoir|bye|à bientôt|à plus|à demain|bonne continuation)[\s!.,?]*$', re.I | re.U),
     "Au revoir. Bonne continuation."),

    (re.compile(r'\b(j\'ai terminé|c\'est tout|c\'est bon|pas d\'autres questions)\b', re.I | re.U),
     "Très bien. N'hésitez pas à revenir si vous avez d'autres questions."),

    # ── Météo / blague / hors-sujet ───────────────────────────────────────────
    (re.compile(r'\b(météo|quel temps|il fait (beau|mauvais|chaud|froid))\b', re.I | re.U),
     "Je ne suis pas connecté à la météo — je me concentre sur le droit du licenciement économique."),

    (re.compile(r'\b(blague|joke|raconte.moi|dis.moi quelque chose d\'amusant|fais.moi rire)\b', re.I | re.U),
     "Je laisse les blagues aux comédiens — mon domaine, c'est le droit du travail. "
     "Puis-je vous aider sur le licenciement économique ?"),

    (re.compile(r'\b(film|série|musique|sport|cuisine|recette|voyage)\b', re.I | re.U),
     "Ce n'est pas mon domaine. Je me spécialise exclusivement en droit du licenciement économique."),

    (re.compile(r'\b(politique|religion|philosophie|histoire)\b', re.I | re.U),
     "Je préfère rester sur le terrain juridique — licenciement économique, procédure, indemnités. "
     "Puis-je vous aider sur ce sujet ?"),

    # ── Doutes / hésitations ──────────────────────────────────────────────────
    (re.compile(r'^(peut.être|je ne sais pas|je sais pas|hm+|euh+)[\s.,!?]*$', re.I | re.U),
     "Pas de problème. Décrivez-moi votre situation et je vous orienterai."),

    (re.compile(r'\b(je ne comprends pas|je comprends pas|c\'est (quoi|pas clair))\b', re.I | re.U),
     "Je vais essayer de clarifier. Quelle partie n'est pas claire ?"),

    # ── Politesse générale ────────────────────────────────────────────────────
    (re.compile(r'^(s\'il vous plaît|svp|please|s\'il te plaît|stp)[\s.,!?]*$', re.I | re.U),
     "Bien sûr. Posez-moi votre question et je ferai de mon mieux pour vous aider."),

    (re.compile(r'\b(excusez.moi|excusez moi|pardon|désolé)\b', re.I | re.U),
     "Pas de souci. Comment puis-je vous aider ?"),

    # ── Longueur / capacité ───────────────────────────────────────────────────
    (re.compile(r'\b(tu (peux|sais|arrives à) (tout|n\'importe quoi)|t\'es fort|impressionnant)\b', re.I | re.U),
     "Merci. Je me concentre sur le licenciement économique — un domaine que j'essaie de couvrir sérieusement."),

    (re.compile(r'\b(tu (connais|sais) tout|tu es parfait|t\'es le meilleur)\b', re.I | re.U),
     "Je connais bien mon domaine, mais je reste limité au droit du licenciement économique."),

    # ── Tests / expérimentaux ─────────────────────────────────────────────────
    (re.compile(r'^(test|testing|ping|pong|hello world|1 2 3)[\s.,!?]*$', re.I | re.U),
     "Je suis opérationnel. Posez-moi une question sur le licenciement économique."),
]

_DEFAULT_RESPONSE = (
    "Je me spécialise en droit du licenciement économique. "
    "Avez-vous une question sur ce sujet ?"
)


def handle(query: str) -> Optional[str]:
    """
    Retourne la réponse canonique pour une requête SMALL_TALK, ou None si aucun pattern.

    None indique que la requête doit être renvoyée au pipeline principal.
    """
    text = query.strip()
    for idx, (pattern, response) in enumerate(_PATTERNS):
        if pattern.search(text):
            logger.info("[SmallTalk] %r → pattern:%d", text[:60], idx)
            return response
    logger.info("[SmallTalk] %r → no pattern (None)", text[:60])
    return None


def handle_or_default(query: str) -> str:
    """Comme handle() mais retourne toujours une réponse (fallback par défaut)."""
    response = handle(query)
    if response is None:
        logger.info("[SmallTalk] %r → _DEFAULT_RESPONSE", query.strip()[:60])
        return _DEFAULT_RESPONSE
    return response
