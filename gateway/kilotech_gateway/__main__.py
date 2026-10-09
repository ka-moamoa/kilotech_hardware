from __future__ import annotations

import argparse

import uvicorn

from kilotech_common.config import load_config
from kilotech_common.util import setup_logging

from .app import create_app
from .config import GatewayConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Kilotech gateway / job queue")
    parser.add_argument("--config", help="YAML config file (or set KILOTECH_GATEWAY_CONFIG)")
    args = parser.parse_args()

    config = load_config(GatewayConfig, env_prefix="KILOTECH_GATEWAY_", path=args.config)
    setup_logging(config.log_level)
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level=config.log_level)


if __name__ == "__main__":
    main()
