"""S2 tests: TaskHandle — public caller-facing task interface.

Validates:
- TaskHandle exposes correct public API (state, done, result, exception, cancel)
- Behavior per task state
- Timeouts
- Exception propagation
- Cancellation requests
"""

import pytest
import threading
import time
from pyron.task import Task, TaskState
from pyron.handle import TaskHandle
from pyron.errors import TaskCancelledError


class TestTaskHandleCreation:
    """TaskHandle creation and basic properties."""

    def test_handle_wraps_task(self):
        """TaskHandle wraps a Task."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert handle._task is task

    def test_handle_has_unique_state(self):
        """Each handle has its own view of the task."""
        task1 = Task(lambda: 1)
        task2 = Task(lambda: 2)
        h1 = TaskHandle(task1)
        h2 = TaskHandle(task2)
        assert h1._task is not h2._task


class TestTaskHandleState:
    """TaskHandle.state() method."""

    def test_state_pending(self):
        """Newly created handle shows PENDING state."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert handle.state() == TaskState.PENDING

    def test_state_completed(self):
        """Handle shows COMPLETED after task runs."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.run()
        assert handle.state() == TaskState.COMPLETED

    def test_state_failed(self):
        """Handle shows FAILED if task raised Exception."""

        def fail():
            raise ValueError("error")

        task = Task(fail)
        handle = TaskHandle(task)
        task.run()
        assert handle.state() == TaskState.FAILED

    def test_state_cancelled(self):
        """Handle shows CANCELLED if task was cancelled."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.cancel()
        assert handle.state() == TaskState.CANCELLED

    def test_state_running(self):
        """Handle shows RUNNING while task is executing."""
        event = threading.Event()

        def slow():
            event.wait()
            return 42

        task = Task(slow)
        handle = TaskHandle(task)

        # Manually transition to RUNNING
        with task._lock:
            task._state = TaskState.RUNNING

        assert handle.state() == TaskState.RUNNING
        event.set()


class TestTaskHandleDone:
    """TaskHandle.done() method."""

    def test_done_false_initially(self):
        """done() is False for PENDING task."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert not handle.done()

    def test_done_true_after_completion(self):
        """done() is True after COMPLETED."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.run()
        assert handle.done()

    def test_done_true_after_failure(self):
        """done() is True after FAILED."""

        def fail():
            raise ValueError()

        task = Task(fail)
        handle = TaskHandle(task)
        task.run()
        assert handle.done()

    def test_done_true_after_cancel(self):
        """done() is True after CANCELLED."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.cancel()
        assert handle.done()


class TestTaskHandleResult:
    """TaskHandle.result() method."""

    def test_result_returns_value(self):
        """result() returns the task's return value."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.run()
        assert handle.result() == 42

    def test_result_waits_for_completion(self):
        """result() blocks until task completes."""
        event = threading.Event()

        def slow_task():
            event.wait()
            return 99

        task = Task(slow_task)
        handle = TaskHandle(task)

        def runner():
            task.run()

        t = threading.Thread(target=runner)
        t.start()

        time.sleep(0.05)
        assert task.state() == TaskState.RUNNING

        result_obtained = [False]

        def waiter():
            r = handle.result()
            result_obtained[0] = (r == 99)

        w = threading.Thread(target=waiter)
        w.start()

        time.sleep(0.05)
        assert not result_obtained[0]  # Still waiting

        event.set()
        w.join(timeout=1.0)
        t.join(timeout=1.0)
        assert result_obtained[0]

    def test_result_timeout(self):
        """result(timeout) raises TimeoutError if task doesn't complete."""
        event = threading.Event()

        def slow_task():
            event.wait()
            return 42

        task = Task(slow_task)
        handle = TaskHandle(task)

        def runner():
            task.run()

        t = threading.Thread(target=runner)
        t.daemon = True
        t.start()

        time.sleep(0.05)

        with pytest.raises(TimeoutError):
            handle.result(timeout=0.1)

        event.set()
        t.join(timeout=1.0)

    def test_result_raises_on_exception(self):
        """result() re-raises the exception from FAILED task."""

        def fail():
            raise ValueError("test error")

        task = Task(fail)
        handle = TaskHandle(task)
        task.run()

        with pytest.raises(ValueError, match="test error"):
            handle.result()

    def test_result_raises_on_cancelled(self):
        """result() raises TaskCancelledError for CANCELLED task."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.cancel()

        with pytest.raises(TaskCancelledError):
            handle.result()

    def test_result_idempotent(self):
        """Calling result() multiple times returns the same value."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.run()

        r1 = handle.result()
        r2 = handle.result()
        r3 = handle.result()

        assert r1 == r2 == r3 == 42

    def test_result_with_args(self):
        """result() works with tasks that have arguments."""

        def add(a, b):
            return a + b

        task = Task(add, 10, 20)
        handle = TaskHandle(task)
        task.run()

        assert handle.result() == 30


class TestTaskHandleException:
    """TaskHandle.exception() method."""

    def test_exception_returns_none_on_success(self):
        """exception() returns None for COMPLETED task."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.run()

        assert handle.exception() is None

    def test_exception_returns_exception_on_failure(self):
        """exception() returns the exception from FAILED task."""

        def fail():
            raise RuntimeError("boom")

        task = Task(fail)
        handle = TaskHandle(task)
        task.run()

        exc = handle.exception()
        assert isinstance(exc, RuntimeError)
        assert str(exc) == "boom"

    def test_exception_raises_on_cancelled(self):
        """exception() raises TaskCancelledError for CANCELLED task."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.cancel()

        with pytest.raises(TaskCancelledError):
            handle.exception()

    def test_exception_waits_for_completion(self):
        """exception() blocks until task completes."""
        event = threading.Event()

        def slow():
            event.wait()
            return 42

        task = Task(slow)
        handle = TaskHandle(task)

        def runner():
            task.run()

        t = threading.Thread(target=runner)
        t.start()

        time.sleep(0.05)

        obtained = [None]

        def waiter():
            obtained[0] = handle.exception()

        w = threading.Thread(target=waiter)
        w.start()

        time.sleep(0.05)
        assert obtained[0] is None  # Still waiting, not set yet

        event.set()
        w.join(timeout=1.0)
        t.join(timeout=1.0)
        assert obtained[0] is None  # Now set to None (task succeeded)

    def test_exception_timeout(self):
        """exception(timeout) raises TimeoutError if task doesn't complete."""
        event = threading.Event()

        def slow():
            event.wait()

        task = Task(slow)
        handle = TaskHandle(task)

        def runner():
            task.run()

        t = threading.Thread(target=runner)
        t.daemon = True
        t.start()

        time.sleep(0.05)

        with pytest.raises(TimeoutError):
            handle.exception(timeout=0.1)

        event.set()
        t.join(timeout=1.0)

    def test_exception_idempotent(self):
        """Calling exception() multiple times returns the same exception."""

        def fail():
            raise ValueError("error")

        task = Task(fail)
        handle = TaskHandle(task)
        task.run()

        exc1 = handle.exception()
        exc2 = handle.exception()
        exc3 = handle.exception()

        assert exc1 is exc2 is exc3
        assert isinstance(exc1, ValueError)


class TestTaskHandleCancel:
    """TaskHandle.cancel() method."""

    def test_cancel_pending_succeeds(self):
        """cancel() succeeds on PENDING task."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)

        success = handle.cancel()
        assert success is True
        assert handle.state() == TaskState.CANCELLED

    def test_cancel_completed_fails(self):
        """cancel() fails on COMPLETED task."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        task.run()

        success = handle.cancel()
        assert success is False
        assert handle.state() == TaskState.COMPLETED

    def test_cancel_failed_fails(self):
        """cancel() fails on FAILED task."""

        def fail():
            raise ValueError()

        task = Task(fail)
        handle = TaskHandle(task)
        task.run()

        success = handle.cancel()
        assert success is False
        assert handle.state() == TaskState.FAILED

    def test_cancel_running_fails(self):
        """cancel() fails on RUNNING task (Phase 1 policy)."""
        event = threading.Event()

        def long():
            event.wait()
            return 42

        task = Task(long)
        handle = TaskHandle(task)

        with task._lock:
            task._state = TaskState.RUNNING

        success = handle.cancel()
        assert success is False
        assert handle.state() == TaskState.RUNNING

        event.set()

    def test_cancel_twice_idempotent(self):
        """Calling cancel() twice: first succeeds, second fails."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)

        success1 = handle.cancel()
        assert success1 is True

        success2 = handle.cancel()
        assert success2 is False

    def test_cancel_raises_in_result(self):
        """result() raises TaskCancelledError after cancel()."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        handle.cancel()

        with pytest.raises(TaskCancelledError):
            handle.result()


class TestTaskHandleConcurrency:
    """TaskHandle thread-safety."""

    def test_multiple_threads_can_wait_on_result(self):
        """Multiple threads can call result() concurrently."""
        event = threading.Event()

        def slow():
            event.wait()
            return 42

        task = Task(slow)
        handle = TaskHandle(task)

        def runner():
            task.run()

        t = threading.Thread(target=runner)
        t.start()

        time.sleep(0.05)

        results = []

        def waiter():
            results.append(handle.result())

        threads = [threading.Thread(target=waiter) for _ in range(5)]
        for w in threads:
            w.start()

        time.sleep(0.05)

        event.set()
        t.join(timeout=1.0)
        for w in threads:
            w.join(timeout=1.0)

        assert results == [42, 42, 42, 42, 42]

    def test_concurrent_cancel_and_result(self):
        """Concurrent cancel() and result() calls are safe."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)

        cancelled = []
        resulted = []

        def canceller():
            try:
                cancelled.append(handle.cancel())
            except Exception as e:
                cancelled.append(e)

        def waiter():
            try:
                r = handle.result()
                resulted.append(r)
            except TaskCancelledError:
                resulted.append("cancelled")
            except Exception as e:
                resulted.append(e)

        t1 = threading.Thread(target=canceller)
        t2 = threading.Thread(target=waiter)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # One of them should have won
        assert len(cancelled) == 1
        assert len(resulted) == 1


class TestTaskHandlePublicAPI:
    """Verify TaskHandle exposes only the public API."""

    def test_handle_does_not_expose_task_run(self):
        """TaskHandle does not expose task.run()."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert not hasattr(handle, "run")

    def test_handle_exposes_state(self):
        """TaskHandle exposes state() method."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert callable(handle.state)

    def test_handle_exposes_done(self):
        """TaskHandle exposes done() method."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert callable(handle.done)

    def test_handle_exposes_result(self):
        """TaskHandle exposes result() method."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert callable(handle.result)

    def test_handle_exposes_exception(self):
        """TaskHandle exposes exception() method."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert callable(handle.exception)

    def test_handle_exposes_cancel(self):
        """TaskHandle exposes cancel() method."""
        task = Task(lambda: 42)
        handle = TaskHandle(task)
        assert callable(handle.cancel)
