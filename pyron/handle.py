"""TaskHandle: public caller-facing view of a task.

A TaskHandle is the only interface callers interact with after spawning a task.
It wraps an internal Task and exposes: state, done, result, exception, and cancel.

State ownership: none (holds a Task reference)
Thread safety: TaskHandle itself is thread-safe for all operations because
  Task is thread-safe. Multiple threads may call result(), cancel(), etc.
  concurrently on the same handle.
"""

from typing import Any, Optional
from .task import Task, TaskState


class TaskHandle:
    """Public handle to a task result.

    Callers receive one of these from runtime.spawn() and use it to:
    - Check the task's state
    - Wait for and retrieve the result or exception
    - Request cancellation

    A handle has no way to force transitions other than cancel(); the task's
    lifecycle is otherwise managed by the worker and runtime.
    """

    def __init__(self, task: Task):
        """Create a handle wrapping an internal task.

        Args:
            task: the internal Task object (not exposed to caller)
        """
        self._task = task

    def state(self) -> TaskState:
        """Current state of the task.

        Returns:
            Current TaskState (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED).
            Note: state may change immediately after this call returns.
        """
        return self._task.state()

    def done(self) -> bool:
        """Whether the task has reached a terminal state.

        Returns:
            True if the task is COMPLETED, FAILED, or CANCELLED; False otherwise.
        """
        return self._task.is_done()

    def result(self, timeout: Optional[float] = None) -> Any:
        """Wait for and return the task's result.

        Blocks until the task completes or timeout expires.

        Args:
            timeout: maximum seconds to wait; None = wait forever

        Returns:
            The return value of the task's callable (if COMPLETED).

        Raises:
            TaskCancelledError: if the task was CANCELLED
            Exception: if the task raised an exception (FAILED)
            TimeoutError: if timeout expires before task finishes
        """
        return self._task.result(timeout=timeout)

    def exception(self, timeout: Optional[float] = None) -> Optional[BaseException]:
        """Wait for and return the task's exception, or None if it completed.

        Blocks until the task completes or timeout expires.

        Args:
            timeout: maximum seconds to wait; None = wait forever

        Returns:
            The exception that was raised (if FAILED), None (if COMPLETED).

        Raises:
            TaskCancelledError: if the task was CANCELLED
            TimeoutError: if timeout expires before task finishes
        """
        return self._task.exception(timeout=timeout)

    def cancel(self) -> bool:
        """Request cancellation of this task.

        Phase 1 policy: only PENDING tasks can be cancelled. A running or
        finished task cannot be cancelled (returns False).

        Returns:
            True if the task is now cancelled; False if it cannot be cancelled
            (already running, completed, failed, or already cancelled).

        Note: This is a request, not a guarantee. Rely on the return value
        and the observable state (via state() or done()), not on assumptions
        about which states are cancellable. This allows the cancellation policy
        to change in a future phase without API changes.
        """
        return self._task.cancel()
