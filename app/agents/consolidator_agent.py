"""ConsolidatorAgent — stub minimal."""
from typing import Any

from app.utils.logger import logger


class ConsolidatorAgent:
    def __init__(self, manager: Any, bus: Any, config: Any) -> None:
        self.manager = manager
        self.bus = bus
        logger.info("ConsolidatorAgent initialisé (stub)")

    def start_background_consolidation(self) -> None: pass
    def stop(self) -> None: pass
