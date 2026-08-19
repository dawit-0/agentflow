"""Abstract base provider and shared event type."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from .sandbox import SandboxConfig


@dataclass
class ProviderEvent:
    """Unified event emitted by all providers.

    ``type`` values match the existing output schema consumed by the frontend:
      - "event"     — lifecycle markers (started, exited, …)
      - "assistant" — incremental text from the model
      - "result"    — final answer / output
      - "text"      — raw / unparsed text
      - "error"     — error message
    """
    type: str
    content: str


class BaseProvider(ABC):
    """Interface that every execution provider must implement."""

    pid: Optional[int] = None  # Only set for subprocess-based providers
    container_name: Optional[str] = None  # Only set when running in a Docker sandbox
    total_cost_usd: float = 0.0  # Captured from the provider's final result event

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        model: str,
        work_dir: str,
        permissions: dict,
        sandbox: Optional[SandboxConfig] = None,
        env: Optional[dict] = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Yield streaming events. The orchestrator consumes these uniformly.

        ``env`` holds decrypted secrets selected for this run, keyed by the
        env var name they should be exposed under.
        """
        ...  # pragma: no cover

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the running execution."""
        ...  # pragma: no cover
