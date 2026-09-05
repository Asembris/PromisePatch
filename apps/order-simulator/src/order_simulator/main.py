"""The simulator's entrypoint: ``order-simulator``.

Its own process, its own port, its own window. Nothing about running it touches PromisePatch,
which is the point: a judge watching the recording has to be able to see that the order changed
in a system PromisePatch does not run.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from order_simulator.app import create_app
from order_simulator.config import get_settings

DEFAULT_PORT = 8100
"""The architecture's port for this system. Published to the host on a high port by compose."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="External Order System — simulator")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=args.host,
        port=args.port,
        log_level=settings.log_level,
        access_log=False,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
