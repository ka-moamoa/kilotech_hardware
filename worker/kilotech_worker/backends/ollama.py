from __future__ import annotations

from typing import Any

import httpx

from .base import Generation, LLMBackend

_METRIC_KEYS = ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration",
                "eval_count", "eval_duration")


class OllamaBackend(LLMBackend):
    """Talks to an Ollama server over its HTTP API (not the `ollama run` CLI)."""

    type = "ollama"

    def __init__(self, url: str = "http://localhost:11434", timeout_s: float = 600,
                 keep_alive: str | None = None):
        self.keep_alive = keep_alive
        self._http = httpx.AsyncClient(base_url=url,
                                       timeout=httpx.Timeout(float(timeout_s), connect=10))

    async def health(self) -> bool:
        try:
            return (await self._http.get("/api/version")).status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        response = await self._http.get("/api/tags")
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]

    async def generate(self, prompt: str, *, model: str, system: str | None = None,
                       options: dict[str, Any] | None = None) -> Generation:
        body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False,
                                "options": options or {}}
        if system:
            body["system"] = system
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        response = await self._http.post("/api/generate", json=body)
        response.raise_for_status()
        data = response.json()
        metrics = {k: data[k] for k in _METRIC_KEYS if k in data}
        if data.get("eval_duration"):
            metrics["tokens_per_s"] = data.get("eval_count", 0) / (data["eval_duration"] / 1e9)
        return Generation(text=data.get("response", "").strip(), model=data.get("model", model),
                          metrics=metrics)

    async def pull(self, model: str) -> None:
        response = await self._http.post("/api/pull", json={"model": model, "stream": False},
                                         timeout=None)
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._http.aclose()
