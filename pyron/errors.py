"""Error types for Pyron runtime.

All errors are specific exception classes; no bare except clauses.
BaseException from a task is re-raised to crash the worker loudly.
"""


class TaskCancelledError(Exception):
    """A task was cancelled and never ran."""

    pass


class RuntimeClosedError(Exception):
    """Runtime was shut down or is shutting down; no new tasks accepted."""

    pass


class RuntimeNotStartedError(Exception):
    """Runtime.spawn() called before Runtime.start()."""

    pass


class SchedulerClosedError(Exception):
    """Internal: scheduler rejected a task after close.

    This is translated to RuntimeClosedError at the API boundary.
    """

    pass
