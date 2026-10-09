from __future__ import annotations

import argparse
import asyncio
import signal

from kilotech_common.config import load_config
from kilotech_common.util import setup_logging

from .agent import WorkerAgent
from .config import WorkerConfig


async def _run(agent: WorkerAgent) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, agent.stop)  # finish in-flight jobs, then exit
        except (NotImplementedError, RuntimeError):
            pass  # Windows: Ctrl+C still raises KeyboardInterrupt
    await agent.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kilotech worker agent")
    parser.add_argument("--config", help="YAML config file (or set KILOTECH_WORKER_CONFIG)")
    args = parser.parse_args()

    config = load_config(WorkerConfig, env_prefix="KILOTECH_WORKER_", path=args.config)
    setup_logging(config.log_level)
    asyncio.run(_run(WorkerAgent(config)))


if __name__ == "__main__":
    main()
