from __future__ import annotations

from typing import Any

import httpx

from .base import Generation, LLMBackend


class OpenAICompatBackend(LLMBackend):
    """Any server exposing the OpenAI `/v1/chat/completions` API: vLLM, llama.cpp server,
    LM Studio, TGI, Ollama's own /v1 endpoint, or a hosted provider."""

    type = "openai"

    def __init__(self, url: str = "http://localhost:8080", api_key: str | None = None,
                 timeout_s: float = 600):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=url.rstrip("/"), headers=headers,
                                       timeout=httpx.Timeout(float(timeout_s), connect=10))

    async def health(self) -> bool:
        try:
            return (await self._http.get("/v1/models")).status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        response = await self._http.get("/v1/models")
        response.raise_for_status()
        return [m["id"] for m in response.json().get("data", [])]

    async def generate(self, prompt: str, *, model: str, system: str | None = None,
                       options: dict[str, Any] | None = None) -> Generation:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        response = await self._http.post("/v1/chat/completions",
                                         json={"model": model, "messages": messages, **(options or {})})
        response.raise_for_status()
        data = response.json()
        return Generation(text=data["choices"][0]["message"]["content"].strip(),
                          model=data.get("model", model), metrics=data.get("usage") or {})

    async def aclose(self) -> None:
        await self._http.aclose()
