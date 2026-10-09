from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_TEMPLATE = (
    "Answer the question using the context below.\n\n"
    "--- Context ---\n{context}\n\n"
    "--- Question ---\n{query}\n"
)


class RagPipeline:
    """Generic retrieve-then-generate. App-specific RAG (extra context, custom prompts)
    belongs in a plugin pipeline in the app repo; this one is for quick experiments.

    input:  {"query": str, "collections": [str]?, "top_k": int?, "max_chars": int?}
    config: template | template_file, collections, top_k, max_chars
    """

    name = "rag"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        if config.get("template_file"):
            self.template = Path(config["template_file"]).read_text(encoding="utf-8")
        else:
            self.template = config.get("template", DEFAULT_TEMPLATE)
        self.collections = config.get("collections")
        self.top_k = int(config.get("top_k", 6))
        self.max_chars = int(config.get("max_chars", 1800))

    async def run(self, job, ctx) -> dict[str, Any]:
        query = job.input.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("input.query is required")
        if ctx.storage is None:
            raise ValueError("the rag pipeline needs storage_urls configured on this worker")

        chunks = await ctx.storage.retrieve(
            query,
            collections=job.input.get("collections", self.collections),
            top_k=int(job.input.get("top_k", self.top_k)),
            max_chars=int(job.input.get("max_chars", self.max_chars)),
        )
        context = "\n\n".join(chunk["text"] for chunk in chunks)
        # str.replace rather than format() so braces in templates or context are harmless.
        prompt = self.template.replace("{context}", context).replace("{query}", query)
        gen = await ctx.llm.generate(prompt, model=ctx.model_for(job), options=job.options)
        return {
            "response": gen.text,
            "model": gen.model,
            "sources": [{k: c[k] for k in ("collection", "source", "line", "score")} for c in chunks],
            "metrics": gen.metrics,
        }
