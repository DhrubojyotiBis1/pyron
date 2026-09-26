"""Runtime: lifecycle, spawn and shutdown for the M:N task pool.

A Runtime owns one Scheduler and N Workers. Callers spawn callables and get
TaskHandles back; M tasks are multiplexed onto the fixed pool of N worker
threads.

Lifecycle (ADR-003): NEW -> RUNNING -> STOPPING -> STOPPED, forward only.

State ownership:
- Runtime state: guarded by self._lifecycle_lock (held O(1), never while
  joining workers, submitting, or running user code)
- Worker list: written in start(), read in shutdown(); start happens-before
  shutdown because shutdown only proceeds from RUNNING
- Scheduler: shared with workers; its own lock guards its queue

Thread safety:
- start(), shutdown(): any thread except a worker thread
- spawn(): any thread; "no task accepted after shutdown begins" is enforced
  by the scheduler's atomic close, not by reading the runtime state
- shutdown() is idempotent; only the call that moves RUNNING -> STOPPING
  does the work, and only that call raises a recorded worker crash.
"""

from enum import Enum
from typing import Any, Callable, Optional
import threading
from .errors import (
    RuntimeClosedError,
    RuntimeNotStartedError,
    SchedulerClosedError,
)
from .handle import TaskHandle
from .scheduler import GlobalQueueScheduler, Scheduler
from .task import Task
from .worker import Worker


class RuntimeState(Enum):
    """Runtime lifecycle states; transitions only move forward."""

    NEW = "NEW"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class Runtime:
    """Fixed pool of N worker threads executing spawned tasks.

    Usage:
        with Runtime(n_workers=4) as rt:
            handle = rt.spawn(fn, arg)
            handle.result()

    Guarantees:
    - Each accepted task runs at most once, and is eventually in a terminal
      state after shutdown() returns (run, or cancelled).
    - After shutdown begins, spawn() raises RuntimeClosedError.

    Non-guarantees (phase-1/scope.md §3):
    - A task that blocks on another queued task can deadlock the pool.
    - Running tasks are never interrupted; shutdown waits for them.
    """

    def __init__(self, n_workers: int, scheduler: Optional[Scheduler] = None):
        """Create a runtime (not started).

        Args:
            n_workers: number of worker threads; required, no default (ADR-003)
            scheduler: task source; defaults to a GlobalQueueScheduler

        Raises:
            TypeError: n_workers is not an int (bool is rejected)
            ValueError: n_workers < 1
        """
        if isinstance(n_workers, bool) or not isinstance(n_workers, int):
            raise TypeError(
                f"n_workers must be an int, got {type(n_workers).__name__}"
            )
        if n_workers < 1:
            raise ValueError(f"n_workers must be at least 1, got {n_workers}")

        self._n_workers = n_workers
        self._scheduler: Scheduler = (
            scheduler if scheduler is not None else GlobalQueueScheduler()
        )
        # Protects _state only.
        self._lifecycle_lock = threading.Lock()
        self._state = RuntimeState.NEW
        self._workers: list[Worker] = []

    @property
    def n_workers(self) -> int:
        """Configured worker count (fixed for the runtime's lifetime)."""
        return self._n_workers

    def state(self) -> RuntimeState:
        """Current lifecycle state (snapshot; may change after return)."""
        with self._lifecycle_lock:
            return self._state

    def start(self) -> None:
        """Create and start the N workers (NEW -> RUNNING).

        Raises:
            RuntimeError: if the runtime is not in the NEW state
        """
        with self._lifecycle_lock:
            if self._state is not RuntimeState.NEW:
                raise RuntimeError(
                    f"start() requires a NEW runtime, state is {self._state.value}"
                )
            self._state = RuntimeState.RUNNING

        # Thread creation happens outside the lock. spawn() may already be
        # called by another thread; the scheduler queues tasks until workers
        # arrive, so nothing is lost.
        workers = [Worker(self._scheduler) for _ in range(self._n_workers)]
        started: list[Worker] = []
        try:
            for worker in workers:
                worker.start()
                started.append(worker)
        except BaseException:
            # Could not bring the pool up (e.g. thread limit). Release the
            # workers that did start so none is left blocked forever.
            self._scheduler.close()
            for task in self._scheduler.drain():
                task.cancel()
            for worker in started:
                worker.join()
            with self._lifecycle_lock:
                self._state = RuntimeState.STOPPED
            raise
        self._workers = started

    def spawn(self, fn: Callable, *args: Any, **kwargs: Any) -> TaskHandle:
        """Submit fn(*args, **kwargs) for execution and return its handle.

        Raises:
            RuntimeNotStartedError: start() has not been called
            RuntimeClosedError: shutdown has begun
        """
        with self._lifecycle_lock:
            state = self._state
        if state is RuntimeState.NEW:
            raise RuntimeNotStartedError("spawn() called before start()")
        if state is not RuntimeState.RUNNING:
            raise RuntimeClosedError("Runtime is shut down")

        task = Task(fn, *args, **kwargs)
        try:
            self._scheduler.submit(task)
        except SchedulerClosedError as e:
            # Lost the race with shutdown; the scheduler's atomic close is
            # the source of truth.
            raise RuntimeClosedError("Runtime is shut down") from e
        return TaskHandle(task)

    def shutdown(self, cancel_pending: bool = False) -> None:
        """Stop the runtime and join all workers (idempotent).

        Args:
            cancel_pending: if True, queued tasks that no worker has claimed
                are cancelled; if False (default, "drain"), workers run them
                all first. Tasks already running always finish.

        Raises:
            RuntimeError: called from one of this runtime's worker threads
                (a worker cannot join itself)
            BaseException: the first crash recorded by a worker, if any
                (raised once, by the call that performed the shutdown)

        Only the call that moves RUNNING -> STOPPING does the work; any
        other call (before start, concurrent, or repeated) returns
        immediately without waiting for it to finish.
        """
        me = threading.current_thread()
        if any(w._thread is me for w in self._workers):
            raise RuntimeError("shutdown() cannot be called from a worker thread")

        with self._lifecycle_lock:
            if self._state is not RuntimeState.RUNNING:
                return
            self._state = RuntimeState.STOPPING

        # Lock released: joining below must never hold the lifecycle lock.
        self._scheduler.close()
        if cancel_pending:
            for task in self._scheduler.drain():
                task.cancel()
        for worker in self._workers:
            worker.join()

        # Final sweep: if every worker crashed, tasks may be stranded in the
        # queue; cancel them so no handle waits forever.
        for task in self._scheduler.drain():
            task.cancel()

        with self._lifecycle_lock:
            self._state = RuntimeState.STOPPED

        for worker in self._workers:
            crash = worker.crash()
            if crash is not None:
                raise crash

    def __enter__(self) -> "Runtime":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()
