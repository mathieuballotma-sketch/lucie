"""Service audio — stub minimal."""
from app.utils.logger import logger

class AudioService:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config
        logger.warning("AudioService : désactivé.")

    def is_ready(self) -> bool: return False
    def start_recording(self) -> None: pass
    def stop_recording(self) -> None: return None
    def transcribe(self, path: str) -> str: return ""
