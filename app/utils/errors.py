# app/utils/errors.py
"""
Exceptions personnalisées pour une gestion d'erreur structurée.
"""

class ToolError(Exception):
    """Exception de base pour les erreurs d'outil."""
    def __init__(self, message: str, code: str = "TOOL_ERROR", suggestion: str = ""):
        self.message = message
        self.code = code
        self.suggestion = suggestion
        super().__init__(message)


class ToolValidationError(ToolError):
    """Erreur de validation des paramètres d'un outil."""
    def __init__(self, message: str, suggestion: str = ""):
        super().__init__(message, code="TOOL_VALIDATION_ERROR", suggestion=suggestion)


class ToolExecutionError(ToolError):
    """Erreur lors de l'exécution d'un outil."""
    def __init__(self, message: str, suggestion: str = ""):
        super().__init__(message, code="TOOL_EXECUTION_ERROR", suggestion=suggestion)


class ToolNotFoundError(ToolError):
    """Outil introuvable."""
    def __init__(self, tool_name: str):
        super().__init__(
            f"Outil '{tool_name}' introuvable",
            code="TOOL_NOT_FOUND",
            suggestion="Vérifiez le nom de l'outil ou consultez la liste des outils disponibles."
        )
class PathExecutionError(ToolError):
    """Erreur lors de l'exécution d'un chemin d'action."""
    def __init__(self, message: str, suggestion: str = ""):
        super().__init__(message, code="PATH_EXECUTION_ERROR", suggestion=suggestion)

class AgentNotFoundError(ToolError):
    """Agent introuvable."""
    def __init__(self, agent_name: str):
        super().__init__(
            f"Agent '{agent_name}' introuvable",
            code="AGENT_NOT_FOUND",
            suggestion="Vérifiez que l'agent est bien enregistré dans le registre."
        )
