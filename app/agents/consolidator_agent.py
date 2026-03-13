"""ConsolidatorAgent — stub minimal."""
from app.utils.logger import logger

class ConsolidatorAgent:
    def __init__(self, manager, bus, config):
        self.manager = manager
        self.bus = bus
        logger.info("ConsolidatorAgent initialisé (stub)")

    def start_background_consolidation(self): pass
    def stop(self): pass
