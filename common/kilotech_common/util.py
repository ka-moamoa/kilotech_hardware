"""Small helpers shared by the nodes: logging setup and plugin imports."""
from __future__ import annotations

import importlib
import logging
from typing import Any


def setup_logging(level: str = "info") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # httpx logs every request at INFO, which floods worker logs with long-poll claims.
    logging.getLogger("httpx").setLevel(max(logging.WARNING, logging.getLogger().level))


def import_object(spec: str) -> Any:
    """Import `package.module:attr` (the same form Python entry points use)."""
    module_name, sep, attr = spec.partition(":")
    if not sep or not attr:
        raise ValueError(f"expected 'module:attr', got {spec!r}")
    obj: Any = importlib.import_module(module_name)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj
