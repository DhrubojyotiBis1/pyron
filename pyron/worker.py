"""Worker: an OS thread that executes tasks from a scheduler.

A Worker owns one OS thread and repeatedly:
1. Fetches a task from the scheduler
2. Runs the task (calls task.run())
3. Repeats until the scheduler reports "no task" (closed and empty)

If a task crashes the worker (re-raises BaseException), the exception is
recorded and allowed to propagate so the crash is visible through the
normal thread-exception path.

State ownership:
- Thread: owned by the worker, created on start()
- Crash record: written by the worker thread only, read by runtime after join

Thread safety:
- Worker.start() and Worker.join() may be called from any thread (e.g., runtime)
- The worker thread runs independently
- Crash record: single-owner (written by worker, read by runtime after join)
"""

from typing import Optional
import threading
from .scheduler import Scheduler
from .task import Task


class Worker:
    """One OS thread that runs tasks from a scheduler.

    Lifecycle:
    - Created: New worker, not started yet
    - start(): Creates and starts the worker thread
    - join(): Waits for the worker thread to exit
    - Exception recorded if the thread crashed (BaseException from a task)
    """

    def __init__(self, scheduler: Scheduler):
        """Create a worker (not yet started).

        Args:
            scheduler: the task source to fetch from
        """
        self._scheduler = scheduler
        self._thread: Optional[threading.Thread] = None
        self._crash_exception: Optional[BaseException] = None

    def start(self) -> None:
        """Create and start the worker thread.

        The worker begins fetching tasks from the scheduler and running them.
        """
        self._thread = threading.Thread(target=self._run, daemon=False)
        self._thread.start()

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the worker thread to exit.

        Args:
            timeout: max seconds to wait; None = wait forever
        """
        if self._thread is None:
            return
        self._thread.join(timeout=timeout)

    def crash(self) -> Optional[BaseException]:
        """Retrieve any exception that crashed the worker.

        Should only be called after join() completes. Returns None if the
        worker exited cleanly.

        Returns:
            The BaseException that crashed the worker, or None.
        """
        return self._crash_exception

    def _run(self) -> None:
        """Worker thread main loop (internal).

        Repeatedly:
        1. Fetch the next task from the scheduler
        2. If no task, exit (scheduler is closed and empty)
        3. Run the task
        4. If BaseException, record it and re-raise
        5. Repeat

        This method is run by the worker thread, not the caller thread.
        """
        try:
            while True:
                task = self._scheduler.next_task()
                if task is None:
                    # Scheduler is closed and has no more work
                    break

                # Run the task (may raise Exception or BaseException)
                try:
                    task.run()
                except BaseException as e:
                    # Record the crash and re-raise so we exit loudly
                    self._crash_exception = e
                    raise
        except BaseException as e:
            # If we exit due to BaseException (and we haven't already
            # recorded it above), record it here. Re-raise so the crash
            # is visible through the thread-exception handler.
            if self._crash_exception is None:
                self._crash_exception = e
            raise
