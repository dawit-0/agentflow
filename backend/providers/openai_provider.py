"""OpenAI API provider for Codex and reasoning models."""

import json
import os
from typing import AsyncIterator, Optional

from .base import BaseProvider, ProviderEvent
from .sandbox import SandboxConfig


class OpenAIProvider(BaseProvider):
    """Execute a prompt via the OpenAI Responses API with streaming."""

    def __init__(self) -> None:
        self.pid: Optional[int] = None  # No subprocess
        self.container_name: Optional[str] = None
        self.stream = None
        self.exit_code: int = 0
        self.stderr_data: str = ""

    async def execute(
        self,
        prompt: str,
        model: str,
        work_dir: str,
        permissions: dict,
        sandbox: Optional[SandboxConfig] = None,
        secrets: Optional[dict[str, str]] = None,
    ) -> AsyncIterator[ProviderEvent]:
        # No subprocess/shell involved — secrets have nothing to inject into.
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            self.exit_code = 1
            self.stderr_data = "OPENAI_API_KEY environment variable is not set"
            yield ProviderEvent(type="error", content=self.stderr_data)
            return

        try:
            from openai import AsyncOpenAI
        except ImportError:
            self.exit_code = 1
            self.stderr_data = "openai package is not installed — run: uv sync"
            yield ProviderEvent(type="error", content=self.stderr_data)
            return

        client = AsyncOpenAI(api_key=api_key)

        yield ProviderEvent(
            type="event",
            content=json.dumps({"event": "api_call_started", "model": model}),
        )

        full_text = ""
        try:
            stream = await client.responses.create(
                model=model,
                input=prompt,
                stream=True,
            )
            self.stream = stream

            async for event in stream:
                if event.type == "response.output_text.delta":
                    full_text += event.delta
                    yield ProviderEvent(type="assistant", content=event.delta)
                elif event.type == "response.completed":
                    # Extract usage/metadata if available
                    pass

            # Yield the final aggregated result
            if full_text:
                yield ProviderEvent(type="result", content=full_text)

            self.exit_code = 0
            self.stderr_data = ""

        except Exception as exc:
            self.exit_code = 1
            self.stderr_data = str(exc)
            yield ProviderEvent(type="error", content=str(exc))

        yield ProviderEvent(
            type="event",
            content=json.dumps({
                "event": "api_call_completed" if self.exit_code == 0 else "api_call_failed",
                "exit_code": self.exit_code,
            }),
        )

    async def cancel(self) -> None:
        if self.stream:
            try:
                await self.stream.close()
            except Exception:
                pass
