"""Couche privacy Beaume — consent flow et préférences locales utilisateur.

Sprint K-8 step 0 : data model + storage atomique. Aucun transport, aucune UI.
"""

from lucie_v1_standalone.privacy.consent import (
    ConsentMode,
    ConsentSchemaVersionError,
    ConsentStatus,
    ConsentStorageError,
    clear_consent,
    get_consent_status,
    has_user_consented,
    set_consent,
)

__all__ = [
    "ConsentMode",
    "ConsentSchemaVersionError",
    "ConsentStatus",
    "ConsentStorageError",
    "clear_consent",
    "get_consent_status",
    "has_user_consented",
    "set_consent",
]
