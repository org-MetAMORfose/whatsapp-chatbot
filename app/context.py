"""Application context for managing lifecycle and graceful shutdown."""

import asyncio
import logging

logger = logging.getLogger(__name__)


class AppContext:
    """Manages app lifecycle and graceful shutdown."""

    def __init__(self) -> None:
        """Initialize app context with shutdown event."""
        self.shutdown_event = asyncio.Event()

    def request_shutdown(self) -> None:
        """Request graceful shutdown."""
        logger.info("Shutdown requested")
        self.shutdown_event.set()

    async def wait_for_shutdown(self) -> None:
        """Wait until shutdown is requested."""
        await self.shutdown_event.wait()

    def is_shutting_down(self) -> bool:
        """Check if shutdown was requested."""
        return self.shutdown_event.is_set()
