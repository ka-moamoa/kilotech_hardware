"""Config loading shared by every node: defaults < YAML file < environment variables.

Env vars are `<PREFIX><FIELD>`, with `__` separating nested keys, e.g.
`KILOTECH_WORKER_BACKEND__URL=http://ollama:11434`. `<PREFIX>CONFIG` names the YAML file.
Empty env values are ignored so compose files can pass `${VAR:-}` through safely.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Any, TypeVar

import yaml
from pydantic import BaseModel, BeforeValidator

T = TypeVar("T", bound=BaseModel)


def _split_list(value: Any) -> Any:
    if isinstance(value, str):
        return [item for item in re.split(r"[,\s]+", value) if item]
    return value


# A list of strings that may also be given as "a,b c" (handy for env vars).
StrList = Annotated[list[str], BeforeValidator(_split_list)]


def _set_nested(data: dict, keys: list[str], value: str) -> None:
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def load_config(model: type[T], *, env_prefix: str, path: str | os.PathLike | None = None,
                environ: dict[str, str] | None = None) -> T:
    environ = os.environ if environ is None else environ
    path = path or environ.get(f"{env_prefix}CONFIG")

    data: dict[str, Any] = {}
    if path:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    for name, value in environ.items():
        if not name.startswith(env_prefix) or name == f"{env_prefix}CONFIG" or value == "":
            continue
        keys = name[len(env_prefix):].lower().split("__")
        _set_nested(data, keys, value)

    return model.model_validate(data)
