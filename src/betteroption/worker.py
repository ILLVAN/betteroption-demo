"""Standalone durable background-worker process."""

from __future__ import annotations

import signal
from threading import Event

from .web import create_app


def main() -> int:
    """Run the app-composed worker until SIGINT or SIGTERM requests shutdown."""

    app = create_app()
    worker = app.state.background_worker
    stopping = Event()

    def request_stop(_signum, _frame) -> None:
        # Signal handlers only flip a thread-safe flag. The main flow performs
        # the cooperative join and lets an in-flight lease expire if needed.
        stopping.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    worker.start()
    try:
        while not stopping.wait(1.0):
            if not worker.is_running:
                raise RuntimeError("background worker thread stopped unexpectedly")
    finally:
        worker.stop(timeout_seconds=10.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
