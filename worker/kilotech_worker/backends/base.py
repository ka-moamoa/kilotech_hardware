"""Model-server interface. Pipelines only see this, so a node can serve its models with
Ollama, any OpenAI-compatible server (vLLM, llama.cpp, LM Studio, ...) or anything else."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Generation:
    text: str
    model: str
    metrics: dict[str, Any] = field(default_factory=dict)


class LLMBackend(ABC):
    type: str = "?"

    @abstractmethod
    async def health(self) -> bool:
        """True once the model server answers."""

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    @abstractmethod
    async def generate(self, prompt: str, *, model: str, system: str | None = None,
                       options: dict[str, Any] | None = None) -> Generation: ...

    async def pull(self, model: str) -> None:
        raise NotImplementedError(f"the {self.type} backend cannot download models")

    async def aclose(self) -> None:
        pass
