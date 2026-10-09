"""Pipeline discovery: built-ins, then installed plugins, then explicit config entries.

Plugins register under the `kilotech.pipelines` entry-point group, e.g. in pyproject.toml:

    [project.entry-points."kilotech.pipelines"]
    kilotech_rag = "kilotech_pipeline.pipeline:KilotechRagPipeline"
"""
from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any

from kilotech_common.util import import_object

from .base import Pipeline, PipelineContext

__all__ = ["Pipeline", "PipelineContext", "load_pipelines", "ENTRY_POINT_GROUP"]

log = logging.getLogger("kilotech.worker.pipelines")

ENTRY_POINT_GROUP = "kilotech.pipelines"
BUILTIN = {
    "generate": "kilotech_worker.pipelines.generate:GeneratePipeline",
    "rag": "kilotech_worker.pipelines.rag:RagPipeline",
}


def load_pipelines(extra: list[str], config: dict[str, dict[str, Any]]) -> dict[str, Pipeline]:
    """`extra` items are "module:attr" (named by the factory's `name`) or "name=module:attr".
    Later sources override earlier ones with the same name. A plugin that fails to load
    is logged and skipped, so the worker still serves everything else."""
    sources: list[tuple[str | None, Any]] = list(BUILTIN.items())
    sources += [(ep.name, ep) for ep in entry_points(group=ENTRY_POINT_GROUP)]
    for item in extra:
        name, sep, spec = item.partition("=")
        sources.append((name, spec) if sep else (None, item))

    pipelines: dict[str, Pipeline] = {}
    for name, source in sources:
        try:
            factory = import_object(source) if isinstance(source, str) else source.load()
            name = name or getattr(factory, "name", None) or str(source)
            pipelines[name] = factory(config.get(name, {}))
        except Exception:
            log.exception("could not load pipeline %r", name or source)
    return pipelines
