from abc import ABC, abstractmethod
from typing import Any


class FrontendAdapter(ABC):
    """
    Base interface for all bot frontends (Discord, Telegram, Web, etc).
    Implementations should provide startup, shutdown, and message dispatch hooks.
    """

    @abstractmethod
    async def start(self) -> None:
        """Start the frontend (connect, authenticate, begin event loop, etc)."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the frontend cleanly (disconnect, cleanup resources, etc)."""
        ...

    @abstractmethod
    async def dispatch_message(self, message: Any) -> None:
        """Dispatch a message or event to this frontend (optional for some frontends)."""
        ...


# In the future, add more methods as needed for advanced orchestration (e.g., health checks, metrics, etc.)
