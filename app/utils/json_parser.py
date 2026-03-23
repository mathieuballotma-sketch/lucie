"""
Module utilitaire pour le parsing JSON robuste.
Utilise json5 en fallback et des regex pour extraire du JSON à partir de texte.
"""

import json
import re
from typing import Any, Optional

from ..utils.logger import logger

# FIX : import avec guard — json5 est Optional
try:
    import json5 as _json5
    JSON5_AVAILABLE = True
except ImportError:
    _json5 = None  # type: ignore[assignment]
    JSON5_AVAILABLE = False
    logger.debug("json5 non disponible, parsing JSON limité au format strict.")


class JSONParseError(Exception):
    """Exception levée quand le parsing JSON échoue."""
    pass


def _try_json5(text: str) -> Any:
    """Tente un parse json5 — lève ValueError si non disponible ou échec."""
    if not JSON5_AVAILABLE or _json5 is None:
        raise ValueError("json5 non disponible")
    return _json5.loads(text)


def parse_json_safely(text: str, expected_type: Optional[type] = None) -> Any:
    """
    Tente de parser du texte en JSON avec plusieurs méthodes :
    1. json.loads() standard
    2. json5.loads() si disponible
    3. Extraction par regex du premier objet ou tableau JSON
    4. Idem après nettoyage markdown

    Args:
        text: La chaîne à parser.
        expected_type: Optionnel, type attendu (dict ou list).

    Returns:
        L'objet Python résultant.

    Raises:
        JSONParseError: Si aucun parsing n'a réussi.
    """
    # Étape 1 : json standard
    try:
        result = json.loads(text)
        if expected_type and not isinstance(result, expected_type):
            raise JSONParseError(
                f"Type inattendu : attendu {expected_type.__name__}, obtenu {type(result).__name__}"
            )
        return result
    except json.JSONDecodeError:
        pass

    # Étape 2 : json5
    if JSON5_AVAILABLE:
        try:
            result = _try_json5(text)
            if expected_type and not isinstance(result, expected_type):
                raise JSONParseError(
                    f"Type inattendu (json5) : attendu {expected_type.__name__}, obtenu {type(result).__name__}"
                )
            return result
        except Exception:
            pass

    # Étape 3 : extraction par regex
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE | re.DOTALL
    ).strip()

    patterns = [
        (r"(\{.*\})", dict),
        (r"(\[.*\])", list),
    ]
    for pattern, typ in patterns:
        match = re.search(pattern, cleaned, re.DOTALL)
        if match:
            candidate = match.group(1)
            try:
                result = json.loads(candidate)
                if expected_type and not isinstance(result, expected_type):
                    continue
                logger.debug(f"JSON extrait par regex : {candidate[:100]}...")
                return result
            except json.JSONDecodeError:
                if JSON5_AVAILABLE:
                    try:
                        result = _try_json5(candidate)
                        if expected_type and not isinstance(result, expected_type):
                            continue
                        logger.debug(f"JSON extrait par regex + json5 : {candidate[:100]}...")
                        return result
                    except Exception:
                        pass
                continue

    logger.error(f"Impossible de parser le JSON : {text[:200]}...")
    raise JSONParseError("Aucune méthode de parsing n'a réussi.")


def safe_json_loads(text: str, default: Any = None, expected_type: Optional[type] = None) -> Any:
    """
    Version tolérante qui retourne une valeur par défaut en cas d'échec.

    Args:
        text: La chaîne à parser.
        default: Valeur retournée en cas d'échec.
        expected_type: Type attendu (optionnel).

    Returns:
        L'objet parsé ou default.
    """
    try:
        return parse_json_safely(text, expected_type)
    except JSONParseError:
        return default
