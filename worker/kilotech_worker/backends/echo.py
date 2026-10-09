from __future__ import annotations

import asyncio
from typing import Any

from .base import Generation, LLMBackend


class EchoBackend(LLMBackend):
    """Fake model that echoes the prompt. Lets the whole cluster run in tests or on a
    laptop without downloading a model. `options.delay_s` simulates a slow generation."""

    type = "echo"

    def __init__(self, models: list[str] | str = "echo", delay_s: float = 0.0):
        self.models = models.split(",") if isinstance(models, str) else list(models)
        self.delay_s = float(delay_s)

    async def health(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return list(self.models)

    async def generate(self, prompt: str, *, model: str, system: str | None = None,
                       options: dict[str, Any] | None = None) -> Generation:
        await asyncio.sleep(float((options or {}).get("delay_s", self.delay_s)))
        return Generation(text=f"echo: {prompt}", model=model, metrics={"chars": len(prompt)})
