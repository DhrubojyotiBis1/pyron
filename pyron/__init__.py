"""Pyron: M:N concurrency runtime for free-threaded Python.

Phase 1 — minimal scheduler with one global queue and N worker threads.
"""

__version__ = "0.0.1-phase1"

from .errors import (
    RuntimeClosedError,
    RuntimeNotStartedError,
    TaskCancelledError,
)
from .handle import TaskHandle
from .runtime import Runtime, RuntimeState
from .task import TaskState

__all__ = [
    "Runtime",
    "RuntimeState",
    "TaskHandle",
    "TaskState",
    "RuntimeClosedError",
    "RuntimeNotStartedError",
    "TaskCancelledError",
]
