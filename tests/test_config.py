import pytest
from pydantic import ValidationError

from kilotech_common.config import load_config
from kilotech_gateway.config import GatewayConfig
from kilotech_worker.config import WorkerConfig


def test_yaml_then_env_override(tmp_path):
    path = tmp_path / "worker.yaml"
    path.write_text(
        "gateway_url: http://gw:8000\n"
        "models: [a, b]\n"
        "backend: {type: ollama, url: http://yaml:11434}\n"
        "pipeline_config: {kilotech_rag: {top_k: 8}}\n"
    )
    env = {
        "KILOTECH_WORKER_CONFIG": str(path),
        "KILOTECH_WORKER_BACKEND__URL": "http://env:11434",
        "KILOTECH_WORKER_STORAGE_URLS": "http://s1:8100, http://s2:8100",
        "KILOTECH_WORKER_CONCURRENCY": "2",
        "KILOTECH_WORKER_ID": "",  # empty values are ignored
        "OTHER": "x",
    }
    cfg = load_config(WorkerConfig, env_prefix="KILOTECH_WORKER_", environ=env)
    assert cfg.gateway_url == "http://gw:8000"
    assert cfg.models == ["a", "b"]
    assert cfg.backend.type == "ollama" and cfg.backend.model_extra["url"] == "http://env:11434"
    assert cfg.storage_urls == ["http://s1:8100", "http://s2:8100"]
    assert cfg.concurrency == 2 and cfg.id is None
    assert cfg.pipeline_config["kilotech_rag"]["top_k"] == 8


def test_space_separated_models_env():
    cfg = load_config(WorkerConfig, env_prefix="KILOTECH_WORKER_",
                      environ={"KILOTECH_WORKER_MODELS": "qwen2.5:3b qwen2.5:7b"})
    assert cfg.models == ["qwen2.5:3b", "qwen2.5:7b"]


def test_typos_are_rejected():
    with pytest.raises(ValidationError):
        load_config(GatewayConfig, env_prefix="KILOTECH_GATEWAY_", environ={"KILOTECH_GATEWAY_LEASE": "5"})
