"""State accessors module."""

from src.core.state import get_state


def log(message: str) -> None:
    """Add message to event log."""
    state = get_state()
    state.event_log.appendleft(message)


def preload() -> None:
    """Initialize simulation."""
    log("Система запущена")
