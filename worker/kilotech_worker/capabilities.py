"""Auto-detected worker labels. Jobs can require them (e.g. {"accel": "nvidia"}) and the
gateway shows them in /v1/cluster. Config `labels` override or extend these."""
from __future__ import annotations

import os
import platform
import shutil
import socket


def _mem_gb() -> float | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (AttributeError, ValueError, OSError):
        return None  # not available on Windows


def detect_labels() -> dict[str, str]:
    labels = {
        "arch": platform.machine().lower(),
        "os": platform.system().lower(),
        "cpus": str(os.cpu_count() or 0),
        "hostname": socket.gethostname(),
        "accel": "nvidia" if shutil.which("nvidia-smi") else "cpu",
    }
    mem = _mem_gb()
    if mem:
        labels["mem_gb"] = str(round(mem))
    return labels
