"""
Module utilitaire pour le parsing JSON robuste.
Utilise json5 en fallback et des regex pour extraire du JSON à partir de texte.
"""

import json
import re
from typing import Any, Optional

from ..utils.logger import logger

# Tentative d'import de json5 pour un parsing tolérant
try:
    import json5

    JSON5_AVAILABLE = True
except ImportError:
    JSON5_AVAILABLE = False
    logger.debug("json5 non disponible, parsing JSON limité au format strict.")


class JSONParseError(Exception):
    """Exception levée quand le parsing JSON échoue."""
    pass


def parse_json_safely(text: str, expected_type: Optional[type] = None) -> Any:
    """
    Tente de parser du texte en JSON avec plusieurs méthodes :
    1. json.loads() standard
    2. json5.loads() si disponible (tolère les commentaires, virgules finales)
    3. Extraction par regex du premier objet ou tableau JSON
    4. Extraction par regex du premier objet ou tableau JSON après nettoyage (enlever markdown)

    Args:
        text: La chaîne à parser.
        expected_type: Optionnel, type attendu (dict ou list). Si fourni, vérifie le type.

    Returns:
        L'objet Python résultant.

    Raises:
        JSONParseError: Si aucun parsing n'a réussi.
    """
    original = text
    # Étape 1 : json.loads standard
    try:
        result = json.loads(text)
        if expected_type and not isinstance(result, expected_type):
            raise JSONParseError(
                f"Type inattendu : attendu {expected_type.__name__}, obtenu {type(result).__name__}"
            )
        return result
    except json.JSONDecodeError:
        pass

    # Étape 2 : json5 (tolérant)
    if JSON5_AVAILABLE:
        try:
            result = json5.loads(text)
            if expected_type and not isinstance(result, expected_type):
                raise JSONParseError(
                    f"Type inattendu (json5) : attendu {expected_type.__name__}, obtenu {type(result).__name__}"
                )
            return result
        except Exception:
            pass

    # Étape 3 : extraction par regex (supprime les marqueurs de code markdown)
    # Enlever les blocs ```json ... ``` ou ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE | re.DOTALL).strip()
    # Chercher un objet {...} ou un tableau [...]
    patterns = [
        (r"(\{.*\})", dict),   # objet
        (r"(\[.*\])", list),   # tableau
    ]
    for pattern, typ in patterns:
        match = re.search(pattern, cleaned, re.DOTALL)
        if match:
            candidate = match.group(1)
            # Essayer de parser ce candidat
            try:
                result = json.loads(candidate)
                if expected_type and not isinstance(result, expected_type):
                    # Si le type ne correspond pas, on continue
                    continue
                logger.debug(f"JSON extrait par regex : {candidate[:100]}...")
                return result
            except json.JSONDecodeError:
                # Si échec, on tente json5
                if JSON5_AVAILABLE:
                    try:
                        result = json5.loads(candidate)
                        if expected_type and not isinstance(result, expected_type):
                            continue
                        logger.debug(f"JSON extrait par regex + json5 : {candidate[:100]}...")
                        return result
                    except Exception:
                        pass
                continue

    # Échec total
    logger.error(f"Impossible de parser le JSON : {original[:200]}...")
    raise JSONParseError("Aucune méthode de parsing n'a réussi.")


def safe_json_loads(text: str, default: Any = None, expected_type: Optional[type] = None) -> Any:
    """
    Version tolérante qui retourne une valeur par défaut en cas d'échec.
    Utile pour les appels où l'absence de JSON n'est pas bloquante.

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