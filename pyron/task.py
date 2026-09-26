"""Task state machine and task representation.

Task: a logical unit of work (callable + args + state + outcome slot).
TaskState: enum of the five task lifecycle states.

A task is guarded by a per-task lock that protects state transitions.
The outcome (result or exception) is written once before the terminal
state is set, and is visible to waiters who observe the completion event.

There is no suspension/waiting state in Phase 1; see phase-1/scope.md §3.
"""

from enum import Enum
from typing import Any, Callable, Optional
import threading


class TaskState(Enum):
    """Five task lifecycle states (ADR-001).

    PENDING  → task created, queued, no worker has claimed it
    RUNNING  → worker claimed and is executing it
    COMPLETED → callable returned; result stored
    FAILED   → callable raised; exception stored
    CANCELLED → cancelled before any worker ran it

    Terminal states: COMPLETED, FAILED, CANCELLED (no transitions out).
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    def is_terminal(self) -> bool:
        """True if this state is final (no further transitions)."""
        return self in (self.COMPLETED, self.FAILED, self.CANCELLED)


# Legal state transitions: (from_state, to_state)
_LEGAL_TRANSITIONS = frozenset([
    (TaskState.PENDING, TaskState.RUNNING),
    (TaskState.PENDING, TaskState.CANCELLED),
    (TaskState.RUNNING, TaskState.COMPLETED),
    (TaskState.RUNNING, TaskState.FAILED),
])


class Task:
    """A logical unit of work: callable + args + guarded state machine.

    Owned state: current state, result/exception outcome slot, completion event.
    Thread safety:
    - State field: guarded by self._lock (held O(1), never under user code).
    - Result/exception: written once by the claiming worker before terminal state.
    - Completion event: set once by worker or canceller; waiters block on it.

    Invariants:
    - A task reaches exactly one terminal state exactly once.
    - Outcome is written before state becomes terminal before event is set.
    - PENDING→RUNNING and PENDING→CANCELLED are mutually exclusive (atomic CAS).
    """

    def __init__(self, fn: Callable, *args, **kwargs):
        """Create a task with a callable and its arguments.

        Args:
            fn: callable to execute
            *args: positional arguments to fn
            **kwargs: keyword arguments to fn
        """
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._id = id(self)  # Unique identifier for logging/debugging

        # Guarded state
        self._lock = threading.Lock()
        self._state = TaskState.PENDING
        self._result: Any = None
        self._exception: Optional[BaseException] = None
        self._completion_event = threading.Event()

    @property
    def id(self) -> int:
        """Unique identifier for this task."""
        return self._id

    def state(self) -> TaskState:
        """Current state (snapshot; may change immediately after)."""
        with self._lock:
            return self._state

    def is_done(self) -> bool:
        """True if the task has reached a terminal state."""
        with self._lock:
            return self._state.is_terminal()

    def result(self, timeout: Optional[float] = None) -> Any:
        """Wait for and return the task's result.

        Args:
            timeout: max seconds to wait; None = wait forever

        Returns:
            The return value of the callable (if COMPLETED).

        Raises:
            TaskCancelledError: if the task was CANCELLED
            Exception: if the task raised an exception (FAILED)
            TimeoutError: if timeout expires before task finishes
        """
        from .errors import TaskCancelledError

        if not self._completion_event.wait(timeout=timeout):
            raise TimeoutError(f"Task {self._id} did not complete within {timeout}s")

        with self._lock:
            if self._state == TaskState.COMPLETED:
                return self._result
            elif self._state == TaskState.FAILED:
                raise self._exception
            elif self._state == TaskState.CANCELLED:
                raise TaskCancelledError(f"Task {self._id} was cancelled")
            else:
                # Should never reach here; completion event should only be
                # set after a terminal state.
                raise RuntimeError(f"Task {self._id} in invalid state {self._state}")

    def exception(self, timeout: Optional[float] = None) -> Optional[BaseException]:
        """Wait for and return the task's exception, or None if it completed.

        Args:
            timeout: max seconds to wait; None = wait forever

        Returns:
            The exception that was raised (if FAILED), None (if COMPLETED).

        Raises:
            TaskCancelledError: if the task was CANCELLED
            TimeoutError: if timeout expires before task finishes
        """
        from .errors import TaskCancelledError

        if not self._completion_event.wait(timeout=timeout):
            raise TimeoutError(f"Task {self._id} did not complete within {timeout}s")

        with self._lock:
            if self._state == TaskState.FAILED:
                return self._exception
            elif self._state == TaskState.COMPLETED:
                return None
            elif self._state == TaskState.CANCELLED:
                raise TaskCancelledError(f"Task {self._id} was cancelled")
            else:
                raise RuntimeError(f"Task {self._id} in invalid state {self._state}")

    def cancel(self) -> bool:
        """Request cancellation of this task.

        Phase 1: only PENDING tasks can be cancelled. Running and finished
        tasks return False (not cancelled).

        Returns:
            True if the task is now cancelled; False if it cannot be cancelled.

        Contract: this is a request, not a guarantee. Callers and tests must
        rely on the returned value and observable state, never on assumptions
        about which tasks can be cancelled. This allows the policy to change
        in a future phase without redesigning the entities.
        """
        with self._lock:
            if self._state != TaskState.PENDING:
                return False

            self._state = TaskState.CANCELLED
            self._completion_event.set()
            return True

    def run(self) -> None:
        """Execute the task (worker thread only).

        Steps:
        1. Try to claim (PENDING → RUNNING). If claim fails (task was cancelled),
           return without running anything.
        2. Call the callable outside the lock.
        3. On normal return: record result, move to COMPLETED.
        4. On Exception: record it, move to FAILED, worker continues.
        5. On BaseException: record it, move to FAILED, re-raise to crash worker.

        The completion event is set after outcome and state are in place.
        """
        # Try to claim the task (CAS: PENDING → RUNNING)
        with self._lock:
            if self._state != TaskState.PENDING:
                # Already cancelled or claimed by another thread (shouldn't happen)
                return
            self._state = TaskState.RUNNING

        # Run the callable outside the lock
        try:
            result = self._fn(*self._args, **self._kwargs)
        except BaseException as e:
            # Record the exception and mark terminal state
            with self._lock:
                self._exception = e
                self._state = TaskState.FAILED
            self._completion_event.set()

            # Distinguish ordinary exceptions from interpreter events
            if isinstance(e, Exception):
                # Ordinary exception: worker continues
                return
            else:
                # BaseException (KeyboardInterrupt, SystemExit, etc.)
                # Mark done and re-raise so worker crashes loudly
                raise
        else:
            # Callable returned normally
            with self._lock:
                self._result = result
                self._state = TaskState.COMPLETED
            self._completion_event.set()
