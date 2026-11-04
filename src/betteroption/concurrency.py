"""Small daemon-thread executor for abandonable, bounded external I/O.

``concurrent.futures.ThreadPoolExecutor`` registers every worker in a private
interpreter-shutdown registry.  Python therefore joins an already-running
HTTP call at process exit even after ``shutdown(wait=False)``.  Explore uses
bounded provider calls whose late results are safe to discard, so that join is
the wrong lifecycle contract: it made a clean Ctrl+C wait for the provider
timeout and a second Ctrl+C printed a traceback.

This executor intentionally implements only the small Future-compatible API
used by BetterOption.  Its workers are daemon threads and are not registered
with ``concurrent.futures.thread``.  Normal ``wait=True`` callers still join;
``wait=False`` callers may abandon in-flight I/O without holding Python open.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, TypeVar


_ResultT = TypeVar("_ResultT")
_WorkItem = tuple[Future[Any], Callable[..., Any], tuple[Any, ...], dict[str, Any]]
_STOP = object()
_CONTROL_CHECKPOINT: ContextVar[Callable[[], None] | None] = ContextVar(
    "betteroption_control_checkpoint",
    default=None,
)


class CooperativeControlFlow(BaseException):
    """Expected worker stop/cancel signal, distinct from process interrupts."""


@contextmanager
def cooperative_control(checkpoint: Callable[[], None] | None):
    """Make one worker checkpoint available to nested provider adapters."""

    token = _CONTROL_CHECKPOINT.set(checkpoint)
    try:
        yield
    finally:
        _CONTROL_CHECKPOINT.reset(token)


def check_cooperative_control() -> None:
    """Raise the active worker's control signal, if this call has one."""

    checkpoint = _CONTROL_CHECKPOINT.get()
    if checkpoint is not None:
        checkpoint()


class DaemonThreadPoolExecutor:
    """A minimal Future executor whose abandoned workers cannot block exit."""

    def __init__(
        self,
        max_workers: int,
        *,
        thread_name_prefix: str = "betteroption-io",
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than zero")
        self.max_workers = max_workers
        self.thread_name_prefix = thread_name_prefix or "betteroption-io"
        self._work: Queue[_WorkItem | object] = Queue()
        self._threads: list[Thread] = []
        self._lock = Lock()
        self._shutdown = False

    def submit(
        self,
        function: Callable[..., _ResultT],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[_ResultT]:
        future: Future[_ResultT] = Future()
        with self._lock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")
            self._work.put((future, function, args, kwargs))
            self._start_workers_locked()
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._lock:
            first_shutdown = not self._shutdown
            self._shutdown = True
            if cancel_futures:
                self._cancel_queued_locked()
            threads = tuple(self._threads)
            if first_shutdown:
                for _thread in threads:
                    self._work.put(_STOP)
        if wait:
            for thread in threads:
                thread.join()

    def __enter__(self) -> DaemonThreadPoolExecutor:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.shutdown(wait=True, cancel_futures=exc_type is not None)

    @property
    def threads(self) -> tuple[Thread, ...]:
        """Expose immutable thread state for lifecycle diagnostics and tests."""

        with self._lock:
            return tuple(self._threads)

    def _start_workers_locked(self) -> None:
        # Count workers which may already be consuming a call as well as work
        # still queued.  Looking only at ``qsize`` races with a fast first
        # worker and can accidentally serialize a burst of submissions.
        desired = min(self.max_workers, len(self._threads) + self._work.qsize())
        while len(self._threads) < desired:
            position = len(self._threads) + 1
            thread = Thread(
                target=self._worker,
                name=f"{self.thread_name_prefix}-{position}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def _cancel_queued_locked(self) -> None:
        retained_stops = 0
        while True:
            try:
                item = self._work.get_nowait()
            except Empty:
                break
            try:
                if item is _STOP:
                    retained_stops += 1
                else:
                    future, _function, _args, _kwargs = item
                    future.cancel()
            finally:
                self._work.task_done()
        for _position in range(retained_stops):
            self._work.put(_STOP)

    def _worker(self) -> None:
        while True:
            item = self._work.get()
            try:
                if item is _STOP:
                    return
                future, function, args, kwargs = item
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    result = function(*args, **kwargs)
                except BaseException as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)
            finally:
                self._work.task_done()
