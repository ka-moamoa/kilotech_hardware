from __future__ import annotations

from typing import Any


class GeneratePipeline:
    """Plain prompt -> completion. input: {"prompt": str, "system": str?}"""

    name = "generate"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def run(self, job, ctx) -> dict[str, Any]:
        prompt = job.input.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("input.prompt is required")
        gen = await ctx.llm.generate(prompt, model=ctx.model_for(job),
                                     system=job.input.get("system"), options=job.options)
        return {"response": gen.text, "model": gen.model, "metrics": gen.metrics}
