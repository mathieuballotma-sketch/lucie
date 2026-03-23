"""
Module diagnostic — auto-diagnostic et rapports d'activité de Lucie.

Exporte :
- HealthCheck  : vérifie l'état de santé de tous les composants
- WeeklyReport : génère un récapitulatif hebdomadaire d'activité
"""

from .health_check import HealthCheck
from .weekly_report import WeeklyReport

__all__ = ["HealthCheck", "WeeklyReport"]
