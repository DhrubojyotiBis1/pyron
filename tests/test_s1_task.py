"""S1 tests: TaskState, Task, and error types.

Validates:
- Task state machine and legal transitions
- Outcome slots (result/exception) are write-once
- Terminal states are immutable
- Cancel vs claim race condition (exactly one wins)
- Exception handling (Exception vs BaseException)
- Timeout behavior
"""

import pytest
import threading
import time
from pyron.errors import TaskCancelledError
from pyron.task import Task, TaskState


class TestTaskState:
    """TaskState enum and transitions."""

    def test_all_states_exist(self):
        """All five states are defined."""
        assert TaskState.PENDING
        assert TaskState.RUNNING
        assert TaskState.COMPLETED
        assert TaskState.FAILED
        assert TaskState.CANCELLED

    def test_terminal_states(self):
        """Correctly identifies terminal vs non-terminal states."""
        assert not TaskState.PENDING.is_terminal()
        assert not TaskState.RUNNING.is_terminal()
        assert TaskState.COMPLETED.is_terminal()
        assert TaskState.FAILED.is_terminal()
        assert TaskState.CANCELLED.is_terminal()


class TestTaskCreation:
    """Task creation and initial state."""

    def test_task_created_pending(self):
        """Newly created task is in PENDING state."""
        task = Task(lambda: 42)
        assert task.state() == TaskState.PENDING
        assert not task.is_done()

    def test_task_has_unique_id(self):
        """Each task has a unique identifier."""
        t1 = Task(lambda: 1)
        t2 = Task(lambda: 2)
        assert t1.id != t2.id

    def test_task_captures_callable_and_args(self):
        """Task stores the callable and arguments."""
        def fn(a, b, c=10):
            return a + b + c

        task = Task(fn, 1, 2, c=3)
        # We can't directly inspect _fn, but we'll test it via run()
        task.run()
        assert task.result() == 6


class TestTaskRun:
    """Task.run() transitions and outcome recording."""

    def test_run_normal_return_completes(self):
        """Task that returns normally → COMPLETED."""
        task = Task(lambda: 42)
        task.run()
        assert task.state() == TaskState.COMPLETED
        assert task.result() == 42

    def test_run_exception_fails(self):
        """Task that raises Exception → FAILED."""

        def failing_task():
            raise ValueError("test error")

        task = Task(failing_task)
        task.run()
        assert task.state() == TaskState.FAILED
        with pytest.raises(ValueError, match="test error"):
            task.result()

    def test_run_exception_available_via_exception_method(self):
        """Raised exception is available via task.exception()."""

        def failing_task():
            raise RuntimeError("boom")

        task = Task(failing_task)
        task.run()
        exc = task.exception()
        assert isinstance(exc, RuntimeError)
        assert str(exc) == "boom"

    def test_run_base_exception_marks_failed_then_reraises(self):
        """BaseException → FAILED state, then re-raise."""

        class CustomBaseException(BaseException):
            pass

        def crashing_task():
            raise CustomBaseException("crash")

        task = Task(crashing_task)
        assert task.state() == TaskState.PENDING

        # run() should mark FAILED then re-raise
        with pytest.raises(CustomBaseException, match="crash"):
            task.run()

        # State should be FAILED
        assert task.state() == TaskState.FAILED
        assert task.is_done()

    def test_run_on_pending_only(self):
        """run() only transitions from PENDING (cancelled tasks skip)."""
        task = Task(lambda: 42)

        # Manually set to CANCELLED (simulating prior cancellation)
        task.cancel()
        assert task.state() == TaskState.CANCELLED

        # Run should be a no-op
        task.run()
        assert task.state() == TaskState.CANCELLED


class TestTaskCancel:
    """Cancellation and cancel-vs-claim race."""

    def test_cancel_pending_succeeds(self):
        """Cancelling a PENDING task succeeds."""
        task = Task(lambda: 42)
        success = task.cancel()
        assert success is True
        assert task.state() == TaskState.CANCELLED

    def test_cancel_completed_fails(self):
        """Cancelling a COMPLETED task fails (already done)."""
        task = Task(lambda: 42)
        task.run()
        success = task.cancel()
        assert success is False
        assert task.state() == TaskState.COMPLETED

    def test_cancel_failed_fails(self):
        """Cancelling a FAILED task fails (already done)."""

        def fail():
            raise ValueError("x")

        task = Task(fail)
        task.run()
        success = task.cancel()
        assert success is False
        assert task.state() == TaskState.FAILED

    def test_cancel_running_fails(self):
        """Cancelling a RUNNING task fails (Phase 1 policy)."""
        event = threading.Event()

        def long_running():
            event.wait()
            return 42

        task = Task(long_running)

        # Transition to RUNNING
        with task._lock:
            task._state = TaskState.RUNNING

        success = task.cancel()
        assert success is False
        assert task.state() == TaskState.RUNNING

        event.set()

    def test_cancel_twice_idempotent(self):
        """Cancelling twice is idempotent."""
        task = Task(lambda: 42)
        assert task.cancel() is True
        assert task.cancel() is False  # Already cancelled


class TestCancelVsClaimRace:
    """The critical race: exactly one of cancel or claim wins."""

    def test_claim_vs_cancel_race_deterministic(self):
        """Claim and cancel race: exactly one wins, consistently."""
        def task_fn():
            return 42

        for attempt in range(100):
            task = Task(task_fn)

            claim_won = False
            cancel_won = False

            def claimer():
                nonlocal claim_won
                # Try to transition PENDING → RUNNING
                with task._lock:
                    if task._state == TaskState.PENDING:
                        task._state = TaskState.RUNNING
                        claim_won = True

            def canceller():
                nonlocal cancel_won
                cancel_won = task.cancel()

            t1 = threading.Thread(target=claimer)
            t2 = threading.Thread(target=canceller)

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # Exactly one should have won (but not both)
            assert (claim_won and not cancel_won) or (cancel_won and not claim_won), \
                f"Attempt {attempt}: claim_won={claim_won}, cancel_won={cancel_won}"

            # State must be terminal
            assert task.state() in (TaskState.RUNNING, TaskState.CANCELLED)


class TestTaskWait:
    """Waiting for task completion with timeout."""

    def test_result_waits_for_completion(self):
        """result() blocks until task completes."""
        event = threading.Event()

        def slow_task():
            event.wait()
            return 99

        task = Task(slow_task)

        def runner():
            task.run()

        t = threading.Thread(target=runner)
        t.start()

        # Wait a bit to ensure run() is in progress
        time.sleep(0.1)
        assert task.state() == TaskState.RUNNING

        # result() should block
        result_event = threading.Event()
        result = [None]

        def waiter():
            result[0] = task.result()
            result_event.set()

        w = threading.Thread(target=waiter)
        w.start()

        time.sleep(0.05)
        assert not result_event.is_set()  # Still waiting

        event.set()  # Let task complete
        result_event.wait(timeout=1.0)
        assert result[0] == 99

        t.join()
        w.join()

    def test_result_timeout(self):
        """result(timeout) raises TimeoutError if task doesn't complete in time."""
        event = threading.Event()

        def slow_task():
            event.wait()  # Never set
            return 42

        task = Task(slow_task)

        def runner():
            task.run()

        t = threading.Thread(target=runner)
        t.daemon = True
        t.start()

        time.sleep(0.05)

        with pytest.raises(TimeoutError):
            task.result(timeout=0.1)

        event.set()
        t.join(timeout=1.0)

    def test_exception_raises_in_result(self):
        """result() re-raises the exception from a FAILED task."""

        def fail():
            raise ValueError("test error")

        task = Task(fail)
        task.run()

        with pytest.raises(ValueError, match="test error"):
            task.result()

    def test_cancelled_raises_in_result(self):
        """result() on a cancelled task raises TaskCancelledError."""
        task = Task(lambda: 42)
        task.cancel()

        with pytest.raises(TaskCancelledError):
            task.result()

    def test_exception_method_returns_none_on_success(self):
        """exception() returns None for a COMPLETED task."""
        task = Task(lambda: 42)
        task.run()
        assert task.exception() is None

    def test_exception_method_returns_exception_on_failure(self):
        """exception() returns the raised exception for a FAILED task."""

        def fail():
            raise RuntimeError("fail")

        task = Task(fail)
        task.run()
        exc = task.exception()
        assert isinstance(exc, RuntimeError)

    def test_exception_method_raises_on_cancelled(self):
        """exception() raises TaskCancelledError for a cancelled task."""
        task = Task(lambda: 42)
        task.cancel()

        with pytest.raises(TaskCancelledError):
            task.exception()


class TestTaskCompletion:
    """Completion event and state finality."""

    def test_is_done_false_initially(self):
        """is_done() is False for PENDING task."""
        task = Task(lambda: 42)
        assert not task.is_done()

    def test_is_done_true_after_completion(self):
        """is_done() is True for COMPLETED task."""
        task = Task(lambda: 42)
        task.run()
        assert task.is_done()

    def test_is_done_true_after_failure(self):
        """is_done() is True for FAILED task."""

        def fail():
            raise ValueError()

        task = Task(fail)
        task.run()
        assert task.is_done()

    def test_is_done_true_after_cancellation(self):
        """is_done() is True for CANCELLED task."""
        task = Task(lambda: 42)
        task.cancel()
        assert task.is_done()

    def test_completion_event_set_on_terminal(self):
        """Completion event is set exactly when task reaches terminal state."""
        task = Task(lambda: 42)
        assert not task._completion_event.is_set()

        task.run()
        assert task._completion_event.is_set()

    def test_outcome_immutable_after_terminal(self):
        """Result is stable across multiple calls (idempotent)."""
        task = Task(lambda: 42)
        task.run()
        result1 = task.result()
        result2 = task.result()
        result3 = task.result()

        # Multiple calls return the same result
        assert result1 == result2 == result3 == 42


class TestTaskWithArgs:
    """Task execution with various argument patterns."""

    def test_positional_args(self):
        """Task executes with positional arguments."""
        def add(a, b):
            return a + b

        task = Task(add, 3, 4)
        task.run()
        assert task.result() == 7

    def test_keyword_args(self):
        """Task executes with keyword arguments."""
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}"

        task = Task(greet, "Alice", greeting="Hi")
        task.run()
        assert task.result() == "Hi, Alice"

    def test_mixed_args(self):
        """Task executes with mixed positional and keyword arguments."""
        def full(a, b, c=10, d=20):
            return a + b + c + d

        task = Task(full, 1, 2, c=3, d=4)
        task.run()
        assert task.result() == 10
