"""Scheduler protocol and GlobalQueueScheduler implementation.

Scheduler is the swappable seam (ADR-002): a protocol that defines how tasks
are accepted, distributed to workers, and drained at shutdown. Different
implementations (global queue, per-worker queues with stealing) satisfy the
same contract, so Worker and Runtime depend only on the protocol, not on a
specific queue topology.

GlobalQueueScheduler is the Phase 1 implementation: a single unbounded FIFO
queue with one lock and a condition variable.

State ownership (GlobalQueueScheduler):
- Queue and closed flag: guarded by self._lock
- Condition variable: for blocking next_task callers and wake-on-close

Thread safety:
- submit(): any thread
- next_task(): worker threads (one per worker)
- close(): runtime shutdown
- drain(): runtime shutdown

Lock invariants:
- Held O(1) time per operation (except drain, O(queued), used only at shutdown)
- No user code runs under the lock (callables run by workers, outside scheduler)
- Atomicity: "reject if closed OR enqueue" is one lock-held operation
"""

from typing import Optional, Protocol
from collections import deque
import threading
from .task import Task
from .errors import SchedulerClosedError


class Scheduler(Protocol):
    """Protocol: task queue and distribution mechanism.

    Different implementations can provide different queue topologies
    (global FIFO, per-worker with stealing, priority queues, etc.) as long
    as they satisfy this contract.
    """

    def submit(self, task: Task) -> None:
        """Accept a task for eventual execution.

        Args:
            task: the task to submit

        Raises:
            SchedulerClosedError: if the scheduler is closed

        Contract:
            - Atomic with respect to close(): a task is either accepted before
              close completes (and will be delivered to a worker or drained) or
              rejected. No task can be accepted after close completes.
        """
        ...

    def next_task(self) -> Optional[Task]:
        """Retrieve the next task for execution.

        Called by worker threads. Blocks until a task is available.

        Returns:
            A Task if one is available, or None only when the scheduler is
            closed AND no work remains for this caller.

        Contract:
            - Blocks (does not spin) while the queue is empty and not closed.
            - Returns the same task to at most one caller.
            - Returns None only when closed and the queue is empty.
        """
        ...

    def close(self) -> None:
        """Stop accepting new tasks (idempotent).

        After this call, submit() will raise SchedulerClosedError. Wakes all
        blocked next_task() callers so they can exit if the queue is empty.

        Contract:
            - Idempotent: calling close() multiple times is safe.
            - submit() rejects immediately after close.
        """
        ...

    def drain(self) -> list[Task]:
        """Atomically remove and return all remaining tasks in the queue.

        Used during shutdown to retrieve pending tasks for cancellation or
        completion.

        Returns:
            A list of all tasks still queued (not yet claimed by a worker).
            May be empty.

        Contract:
            - Atomic: the returned list is a snapshot at a single point in time.
        """
        ...


class GlobalQueueScheduler:
    """Phase 1 Scheduler: single unbounded FIFO queue (ADR-002).

    Owned state:
    - Queue and closed flag, both guarded by self._lock

    Thread safety:
    - Lock is held O(1) time per operation
    - Condition variable wakes blocked next_task() callers on close
    - No user code runs under the lock
    """

    def __init__(self):
        """Create a scheduler with an empty queue."""
        self._queue: deque[Task] = deque()
        self._closed = False
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    def submit(self, task: Task) -> None:
        """Submit a task for execution.

        Args:
            task: the task to submit

        Raises:
            SchedulerClosedError: if the scheduler is already closed
        """
        with self._condition:
            if self._closed:
                raise SchedulerClosedError("Scheduler is closed")
            self._queue.append(task)
            self._condition.notify()  # Wake one waiting worker

    def next_task(self) -> Optional[Task]:
        """Retrieve the next task, blocking until one is available or closed.

        Returns:
            A Task if the queue is not empty, or None if the scheduler is
            closed and the queue is empty.
        """
        with self._condition:
            # Wait while the queue is empty and the scheduler is not closed
            while len(self._queue) == 0 and not self._closed:
                self._condition.wait()

            # When we wake up, either:
            # 1. A task was added, or
            # 2. The scheduler was closed
            if len(self._queue) > 0:
                return self._queue.popleft()
            else:
                # Closed and queue is empty
                return None

    def close(self) -> None:
        """Stop accepting new tasks and wake all waiting workers.

        Idempotent: calling close() multiple times is safe.
        """
        with self._condition:
            self._closed = True
            self._condition.notify_all()  # Wake all waiting workers

    def drain(self) -> list[Task]:
        """Atomically remove and return all tasks still in the queue.

        Returns:
            List of all queued tasks (not yet claimed by a worker).
        """
        with self._condition:
            result = list(self._queue)
            self._queue.clear()
            return result
