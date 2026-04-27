"""Renderer Markdown -> NSAttributedString (H7 Sprint S1).

Parser maison sans dépendance externe. Reconnaît :
- Titres `# `, `## `, `### `
- Gras `**texte**`
- Italique `*texte*`
- Code inline `` `texte` ``
- Listes `- item` et `1. item`
- Paragraphes simples (line-height 1.4, paragraph spacing 6pt)

Le rendu finalise les attributs hiérarchiques (font, weight, paragraph style,
color) sur la sortie streaming brute. Le streaming token-by-token reste
géré par hud_native.py avec un rendu basique (intact). À la fin du
streaming, hud_native.py appelle `render(...)` pour remplacer la plage
de texte par le rendu Markdown propre.

Réutilisable par H16 (bloc rédaction in-window, S2).
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple

import AppKit
import Foundation


# ─── Patterns inline (ordre important : bold avant italic) ───────────────────
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")

# Préfixes liste / titres
_LIST_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_LIST_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")


def _base_paragraph_style() -> Any:
    style = AppKit.NSMutableParagraphStyle.alloc().init()
    style.setLineHeightMultiple_(1.4)
    style.setParagraphSpacing_(6.0)
    return style


def _heading_paragraph_style(spacing_before: float, spacing_after: float) -> Any:
    style = AppKit.NSMutableParagraphStyle.alloc().init()
    style.setLineHeightMultiple_(1.25)
    style.setParagraphSpacing_(spacing_after)
    style.setParagraphSpacingBefore_(spacing_before)
    return style


def _list_paragraph_style(indent: float = 16.0) -> Any:
    style = AppKit.NSMutableParagraphStyle.alloc().init()
    style.setLineHeightMultiple_(1.35)
    style.setParagraphSpacing_(2.0)
    style.setHeadIndent_(indent)
    style.setFirstLineHeadIndent_(0.0)
    return style


def _label_color() -> Any:
    return AppKit.NSColor.labelColor()


def _secondary_color() -> Any:
    return AppKit.NSColor.secondaryLabelColor()


def _code_background() -> Any:
    # NSColor.systemFill avec alpha ~0.4 → fond léger qui rend bien en HUD vibrancy
    return AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.5, 0.18)


def _font(size: float, weight: Any) -> Any:
    return AppKit.NSFont.systemFontOfSize_weight_(size, weight)


def _mono_font(size: float) -> Any:
    return AppKit.NSFont.monospacedSystemFontOfSize_weight_(
        size, AppKit.NSFontWeightRegular
    )


def _block_kind(line: str) -> Tuple[str, str, int]:
    """Identifie le type de bloc d'une ligne. Retourne (kind, content, level).

    kind ∈ {"heading", "list_bullet", "list_numbered", "paragraph", "blank"}
    level = 1/2/3 pour heading, 0 sinon.
    """
    if not line.strip():
        return ("blank", "", 0)
    m = _HEADING_RE.match(line)
    if m:
        hashes, content = m.group(1), m.group(2)
        return ("heading", content, len(hashes))
    m = _LIST_BULLET_RE.match(line)
    if m:
        return ("list_bullet", m.group(1), 0)
    m = _LIST_NUMBERED_RE.match(line)
    if m:
        return ("list_numbered", m.group(1), 0)
    return ("paragraph", line, 0)


def _apply_inline(
    attributed: Any,
    body_text: str,
    base_attrs: dict,
    base_offset: int,
) -> None:
    """Applique gras/italique/code inline sur la plage [base_offset, base_offset+len(body_text)).

    Suppose que `attributed` contient déjà `body_text` à `base_offset` avec `base_attrs`.
    On ajoute les attributs *différentiels* (font weight, italic trait, mono font, bg).
    """
    # Gras — on remplace la font par la version semibold
    base_font = base_attrs.get(AppKit.NSFontAttributeName)
    if base_font is None:
        return
    base_size = base_font.pointSize()

    for m in _BOLD_RE.finditer(body_text):
        start = base_offset + m.start()
        length = m.end() - m.start()
        bold_font = AppKit.NSFont.systemFontOfSize_weight_(
            base_size, AppKit.NSFontWeightSemibold
        )
        attributed.addAttribute_value_range_(
            AppKit.NSFontAttributeName,
            bold_font,
            Foundation.NSMakeRange(start, length),
        )

    # Italique
    for m in _ITALIC_RE.finditer(body_text):
        start = base_offset + m.start()
        length = m.end() - m.start()
        italic_font = AppKit.NSFontManager.sharedFontManager().convertFont_toHaveTrait_(
            base_font, AppKit.NSItalicFontMask
        )
        if italic_font is not None:
            attributed.addAttribute_value_range_(
                AppKit.NSFontAttributeName,
                italic_font,
                Foundation.NSMakeRange(start, length),
            )

    # Code inline
    for m in _CODE_RE.finditer(body_text):
        start = base_offset + m.start()
        length = m.end() - m.start()
        attributed.addAttribute_value_range_(
            AppKit.NSFontAttributeName,
            _mono_font(base_size),
            Foundation.NSMakeRange(start, length),
        )
        attributed.addAttribute_value_range_(
            AppKit.NSBackgroundColorAttributeName,
            _code_background(),
            Foundation.NSMakeRange(start, length),
        )


def _heading_attrs(level: int) -> dict:
    if level == 1:
        font = _font(18.0, AppKit.NSFontWeightSemibold)
        para = _heading_paragraph_style(8.0, 6.0)
    elif level == 2:
        font = _font(15.0, AppKit.NSFontWeightSemibold)
        para = _heading_paragraph_style(6.0, 4.0)
    else:
        font = _font(13.0, AppKit.NSFontWeightMedium)
        para = _heading_paragraph_style(4.0, 3.0)
    return {
        AppKit.NSFontAttributeName: font,
        AppKit.NSForegroundColorAttributeName: _label_color(),
        AppKit.NSParagraphStyleAttributeName: para,
    }


def _paragraph_attrs(base_size: float = 12.5) -> dict:
    return {
        AppKit.NSFontAttributeName: _font(base_size, AppKit.NSFontWeightRegular),
        AppKit.NSForegroundColorAttributeName: _label_color(),
        AppKit.NSParagraphStyleAttributeName: _base_paragraph_style(),
    }


def _list_attrs(base_size: float = 12.5) -> dict:
    return {
        AppKit.NSFontAttributeName: _font(base_size, AppKit.NSFontWeightRegular),
        AppKit.NSForegroundColorAttributeName: _label_color(),
        AppKit.NSParagraphStyleAttributeName: _list_paragraph_style(),
    }


def _append_run(
    attributed: Any,
    text: str,
    attrs: dict,
    inline_body: bool = True,
) -> None:
    """Ajoute `text` avec `attrs` dans `attributed`, puis applique les attrs inline."""
    if not text:
        return
    base_offset = attributed.length()
    run = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
    attributed.appendAttributedString_(run)
    if inline_body:
        _apply_inline(attributed, text, attrs, base_offset)


def render(text: str, base_size: float = 12.5) -> Any:
    """Rend du Markdown en NSAttributedString.

    Parser maison ligne par ligne, robuste aux Markdown malformés (ex. `**non
    fermé`) — les patterns non matchés restent en texte brut.

    Args:
        text: Markdown brut (\\n-séparé).
        base_size: taille de la police de base pour paragraphes/listes.

    Returns:
        NSAttributedString prêt à être inséré dans un NSTextStorage.
    """
    attributed = AppKit.NSMutableAttributedString.alloc().init()
    if not text:
        return attributed

    lines = text.split("\n")
    para_attrs = _paragraph_attrs(base_size)
    list_attrs = _list_attrs(base_size)

    for idx, line in enumerate(lines):
        kind, content, level = _block_kind(line)
        is_last = idx == len(lines) - 1
        suffix = "" if is_last else "\n"

        if kind == "blank":
            _append_run(attributed, suffix, para_attrs, inline_body=False)
            continue

        if kind == "heading":
            attrs = _heading_attrs(level)
            _append_run(attributed, content + suffix, attrs)
            continue

        if kind == "list_bullet":
            bullet_run = "•  "
            _append_run(attributed, bullet_run, list_attrs, inline_body=False)
            _append_run(attributed, content + suffix, list_attrs)
            continue

        if kind == "list_numbered":
            # On laisse le numéro original tel qu'écrit par le rédacteur (1. 2. ...)
            m = _LIST_NUMBERED_RE.match(line)
            number_match = re.match(r"^\s*(\d+)\.\s+", line)
            number = number_match.group(1) if number_match else "1"
            number_run = f"{number}.  "
            _append_run(attributed, number_run, list_attrs, inline_body=False)
            _append_run(attributed, content + suffix, list_attrs)
            continue

        # paragraph
        _append_run(attributed, content + suffix, para_attrs)

    return attributed


__all__ = ["render"]
