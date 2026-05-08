"""Formatte une réponse Markdown brute en texte plat prêt à coller.

Usage côté HUD : ``copyResponseAction_`` appelle ``format_response_for_copy``
avant de pousser le texte au NSPasteboard. Permet à l'avocat de coller
directement dans Mail/Word/Outlook sans avoir des ``[REF: L.1232-1]``
ni des ``**gras**`` qui traînent.

Format des citations transformées : ``[REF: L.1232-1]`` →
``(L.1232-1 du Code du travail)``.

Module isolé (pas de dépendance UI/AppKit) pour pouvoir le tester sans
PyObjC.
"""

from __future__ import annotations

import re

# Capture une citation de type [REF: L.1232-1], [L.1232-1], [L1232-1],
# [l 1232 1], etc. Tolérant aux espaces, casse et points.
_REF_RE = re.compile(
    r"\[(?:REF\s*:\s*)?([Ll]\.?\s*\d{1,4}(?:[\s\-.]\d{1,3})?(?:[\s\-.]\d{1,3})?)\]"
)


def _normalize_article(raw: str) -> str:
    """``L1232-1``, ``L 1232 1``, ``l.1232-1`` → ``L.1232-1``.

    Forme canonique : ``L.NNNN-N`` (préfixe L., chiffres séparés par tiret).
    Les espaces internes (``L 1232 1``) et points (``L.1232.1``) jouent le
    rôle de séparateur au même titre que le tiret.
    """
    s = raw.upper().strip()
    # Sépare le L initial du reste, puis remplace tous les séparateurs
    # internes (espaces, points, tirets) par un tiret unique.
    m = re.match(r"^L\.?\s*(.+)$", s)
    if not m:
        return s
    body = m.group(1)
    body = re.sub(r"[\s\-.]+", "-", body).strip("-")
    return f"L.{body}"


def _code_for_article(article_id: str) -> str:
    """Devine le code à partir du numéro d'article.

    Beaume V1 ne couvre que le droit social → fallback "Code du travail".
    Si extension future à la sécu sociale, baux commerciaux, etc., enrichir
    cette heuristique avec un mapping plus fin.
    """
    aid = article_id.upper().replace(".", "").replace("-", "").replace(" ", "")
    m = re.match(r"^L(\d+)", aid)
    if not m:
        return "Code du travail"
    # Beaume V1 = Code du travail uniquement.
    return "Code du travail"


def _replace_ref(match: re.Match[str]) -> str:
    article = _normalize_article(match.group(1))
    code = _code_for_article(article)
    return f"({article} du {code})"


def _strip_markdown(text: str) -> str:
    """Strip Markdown de surface : gras, italique, titres, listes, code inline.

    Volontairement minimal : l'avocat veut un texte propre pour Word/Mail,
    pas une conversion HTML/PDF. Les sauts de ligne sont préservés.
    """
    # Gras **xxx** → xxx
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # Italique *xxx* (pas double-étoile)
    text = re.sub(r"(?<![*\\])\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    # Code inline `xxx` → xxx
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Titres ## Titre → Titre (en début de ligne)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Listes "- item" → "• item" (puce typographique propre)
    text = re.sub(r"^(\s*)-\s+", r"\1• ", text, flags=re.MULTILINE)
    return text


def format_response_for_copy(markdown_text: str) -> str:
    """Pipeline complet : citations transformées + Markdown stripé.

    Vide → vide. Sinon retourne la string nettoyée, prête à coller.
    """
    if not markdown_text:
        return ""
    text = _REF_RE.sub(_replace_ref, markdown_text)
    text = _strip_markdown(text)
    return text.strip()
