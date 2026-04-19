"""Dialogue — 3-modes conversationnels (non branché au pipeline principal)."""

from .dialogue_manager import DialogueManager, DialogueState
from .intent_classifier import Intent, classify
from .small_talk_handler import handle, handle_or_default

__all__ = [
    "DialogueManager",
    "DialogueState",
    "Intent",
    "classify",
    "handle",
    "handle_or_default",
]
