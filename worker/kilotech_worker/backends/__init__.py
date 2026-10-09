from kilotech_common.util import import_object

from .base import Generation, LLMBackend

__all__ = ["Generation", "LLMBackend", "build_backend"]

BACKENDS = {
    "ollama": "kilotech_worker.backends.ollama:OllamaBackend",
    "openai": "kilotech_worker.backends.openai_compat:OpenAICompatBackend",
    "echo": "kilotech_worker.backends.echo:EchoBackend",
}


def build_backend(config) -> LLMBackend:
    """`config.type` is a registered name or `module:Class`; other keys become kwargs."""
    cls = import_object(BACKENDS.get(config.type, config.type))
    return cls(**config.model_dump(exclude={"type"}))
