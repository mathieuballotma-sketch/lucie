"""
Hiérarchie des exceptions pour Agent Lucide.
Toutes les exceptions personnalisées héritent de LucidError.
"""


class LucidError(Exception):
    """Exception de base pour toutes les erreurs de l'application."""


# Erreurs LLM


class LLMError(LucidError):
    """Erreur de base pour les problèmes liés au LLM."""


class LLMConnectionError(LLMError):
    """Impossible de se connecter au service LLM."""


class LLMTimeoutError(LLMError):
    """Timeout lors d'un appel LLM."""


class LLMResponseError(LLMError):
    """Réponse invalide du LLM (format, contenu)."""


class LLMModelNotFoundError(LLMError):
    """Modèle LLM demandé non disponible."""


# Erreurs de vision


class VisionError(LucidError):
    """Erreur de base pour le module vision."""


class TesseractNotFoundError(VisionError):
    """Tesseract OCR non installé ou introuvable."""


class AccessibilityError(VisionError):
    """Erreur d'accessibilité macOS."""


# Erreurs audio


class AudioError(LucidError):
    """Erreur de base pour le module audio."""


class AudioDeviceError(AudioError):
    """Périphérique audio non disponible ou inaccessible."""


class TranscriptionError(AudioError):
    """Erreur lors de la transcription audio."""


# Erreurs RAG


class RAGError(LucidError):
    """Erreur de base pour le service RAG."""


class IndexingError(RAGError):
    """Erreur lors de l'indexation d'un document."""


# Erreurs d'actions


class ActionError(LucidError):
    """Erreur de base pour l'exécution d'actions système."""


class AppleScriptError(ActionError):
    """Erreur lors de l'exécution d'un script AppleScript."""


class FileOperationError(ActionError):
    """Erreur lors d'une opération sur les fichiers."""


# Erreurs de configuration


class ConfigError(LucidError):
    """Erreur de configuration (fichier manquant, valeur invalide)."""


# Erreurs de planification


class PlanningError(LucidError):
    """Erreur lors de la génération ou de l'exécution d'un plan."""


class ToolExecutionError(PlanningError):
    """Erreur lors de l'exécution d'un outil par un agent."""


class AgentNotFoundError(PlanningError):
    """Agent demandé introuvable."""
