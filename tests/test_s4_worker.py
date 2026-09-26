"""S4 tests: Worker — OS thread that runs tasks from a scheduler.

Validates:
- Worker runs tasks from the scheduler
- Worker exits when scheduler returns no task
- Worker records crashes (BaseException)
- Worker handles multiple tasks sequentially
- Worker joins correctly
- Crash is propagated through thread-exception path
"""

import pytest
import threading
import time
from pyron.task import Task, TaskState
from pyron.scheduler import GlobalQueueScheduler
from pyron.worker import Worker


class TestWorkerBasic:
    """Basic worker functionality."""

    def test_worker_created_not_started(self):
        """Worker created but not started."""
        scheduler = GlobalQueueScheduler()
        worker = Worker(scheduler)
        assert worker._thread is None

    def test_worker_start_creates_thread(self):
        """start() creates and starts a thread."""
        scheduler = GlobalQueueScheduler()
        scheduler.close()  # So worker will exit immediately

        worker = Worker(scheduler)
        worker.start()
        assert worker._thread is not None
        assert worker._thread.is_alive()

        worker.join(timeout=1.0)
        assert not worker._thread.is_alive()

    def test_worker_joins_successfully(self):
        """join() waits for thread to exit."""
        scheduler = GlobalQueueScheduler()
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()

        # Thread should be running
        assert worker._thread.is_alive()

        # Join waits for it to exit
        worker.join(timeout=1.0)
        assert not worker._thread.is_alive()

    def test_worker_join_timeout(self):
        """join(timeout) respects the timeout."""
        event = threading.Event()

        def endless_task():
            event.wait()

        scheduler = GlobalQueueScheduler()
        task = Task(endless_task)
        scheduler.submit(task)

        worker = Worker(scheduler)
        worker.start()

        try:
            time.sleep(0.1)  # Let worker claim and run the task
            assert worker._thread.is_alive()

            # Join with short timeout should return even though thread is alive
            start = time.time()
            worker.join(timeout=0.05)
            elapsed = time.time() - start

            # Should have returned quickly (not waited long)
            assert elapsed < 0.5
            assert worker._thread.is_alive()  # Still running
        finally:
            # Release the task and close so the worker exits (never leak a blocked thread)
            event.set()
            scheduler.close()
            worker.join(timeout=2.0)
        assert not worker._thread.is_alive()

    def test_worker_crash_property(self):
        """crash() returns None for clean exit."""
        scheduler = GlobalQueueScheduler()
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        assert worker.crash() is None


class TestWorkerTaskExecution:
    """Worker executing tasks."""

    def test_worker_runs_single_task(self):
        """Worker executes a single task."""
        scheduler = GlobalQueueScheduler()
        task = Task(lambda: 42)
        scheduler.submit(task)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        assert task.state() == TaskState.COMPLETED
        assert task.result() == 42
        assert worker.crash() is None

    def test_worker_runs_multiple_tasks(self):
        """Worker executes multiple tasks sequentially."""
        scheduler = GlobalQueueScheduler()

        tasks = [Task(lambda i=i: i) for i in range(5)]
        for t in tasks:
            scheduler.submit(t)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        # All tasks should be completed
        for task in tasks:
            assert task.state() == TaskState.COMPLETED
            assert task.is_done()

        assert worker.crash() is None

    def test_worker_task_with_exception(self):
        """Worker handles task that raises Exception."""

        def fail():
            raise ValueError("expected error")

        scheduler = GlobalQueueScheduler()
        task = Task(fail)
        scheduler.submit(task)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        # Task should be FAILED
        assert task.state() == TaskState.FAILED

        # Worker should continue (Exception is not BaseException)
        assert worker.crash() is None

    def test_worker_task_with_base_exception(self):
        """Worker task raises BaseException: worker crashes and records it."""

        class CustomBaseException(BaseException):
            pass

        def crashing_task():
            raise CustomBaseException("crash")

        scheduler = GlobalQueueScheduler()
        task = Task(crashing_task)
        scheduler.submit(task)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        # Task should be FAILED
        assert task.state() == TaskState.FAILED

        # Worker should have recorded the crash
        crash = worker.crash()
        assert crash is not None
        assert isinstance(crash, CustomBaseException)
        assert str(crash) == "crash"

    def test_worker_continues_after_exception(self):
        """Worker continues after Exception, not after BaseException."""

        def fail():
            raise ValueError("error")

        def succeed():
            return 99

        scheduler = GlobalQueueScheduler()

        task1 = Task(fail)
        task2 = Task(succeed)

        scheduler.submit(task1)
        scheduler.submit(task2)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        # Both should be done
        assert task1.state() == TaskState.FAILED
        assert task2.state() == TaskState.COMPLETED
        assert task2.result() == 99

        # Worker should not have crashed
        assert worker.crash() is None

    def test_worker_exits_when_no_task(self):
        """Worker exits cleanly when scheduler returns no task."""
        scheduler = GlobalQueueScheduler()
        # Don't submit any tasks, just close

        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        # Should exit cleanly
        assert not worker._thread.is_alive()
        assert worker.crash() is None


class TestWorkerCrashHandling:
    """Worker crash recording and propagation."""

    def test_worker_records_keyboard_interrupt(self):
        """Worker records KeyboardInterrupt as crash."""

        def interrupted():
            raise KeyboardInterrupt()

        scheduler = GlobalQueueScheduler()
        task = Task(interrupted)
        scheduler.submit(task)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        # Worker should have recorded the crash
        crash = worker.crash()
        assert crash is not None
        assert isinstance(crash, KeyboardInterrupt)

    def test_worker_records_system_exit(self):
        """Worker records SystemExit as crash."""

        def exiting():
            raise SystemExit(1)

        scheduler = GlobalQueueScheduler()
        task = Task(exiting)
        scheduler.submit(task)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        crash = worker.crash()
        assert crash is not None
        assert isinstance(crash, SystemExit)

    def test_multiple_tasks_before_crash(self):
        """Multiple tasks run before one crashes the worker."""

        class CrashException(BaseException):
            pass

        def succeed():
            return "ok"

        def crash():
            raise CrashException("oops")

        scheduler = GlobalQueueScheduler()

        task1 = Task(succeed)
        task2 = Task(succeed)
        task3 = Task(crash)

        scheduler.submit(task1)
        scheduler.submit(task2)
        scheduler.submit(task3)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        # First two should be complete
        assert task1.state() == TaskState.COMPLETED
        assert task2.state() == TaskState.COMPLETED

        # Third should have failed and crashed the worker
        assert task3.state() == TaskState.FAILED
        crash = worker.crash()
        assert isinstance(crash, CrashException)


class TestWorkerConcurrency:
    """Worker with multiple workers or concurrent operations."""

    def test_multiple_workers_same_scheduler(self):
        """Multiple workers can fetch from the same scheduler."""
        scheduler = GlobalQueueScheduler()

        num_tasks = 20
        tasks = [Task(lambda i=i: i) for i in range(num_tasks)]
        for t in tasks:
            scheduler.submit(t)
        scheduler.close()

        # Start 3 workers
        workers = [Worker(scheduler) for _ in range(3)]
        for w in workers:
            w.start()

        # Join all
        for w in workers:
            w.join(timeout=1.0)

        # All tasks should be complete
        for task in tasks:
            assert task.state() == TaskState.COMPLETED
            assert task.is_done()

        # No crashes
        for w in workers:
            assert w.crash() is None

    def test_worker_and_concurrent_task_submit(self):
        """Worker runs tasks while new tasks are being submitted."""
        scheduler = GlobalQueueScheduler()

        results = {"submitted": 0, "completed": 0}
        lock = threading.Lock()

        def incrementer():
            with lock:
                results["completed"] += 1

        # Start worker
        worker = Worker(scheduler)
        worker.start()

        # Submit tasks from another thread
        def submitter():
            for i in range(10):
                task = Task(incrementer)
                scheduler.submit(task)
                with lock:
                    results["submitted"] += 1
                time.sleep(0.01)

            scheduler.close()

        s = threading.Thread(target=submitter)
        s.start()

        # Wait for both to complete
        s.join()
        worker.join(timeout=2.0)

        assert results["submitted"] == 10
        assert results["completed"] == 10
        assert worker.crash() is None

    def test_worker_join_timeout_with_hanging_task(self):
        """join(timeout) returns even if worker task hangs."""
        event = threading.Event()

        def hanging():
            event.wait()

        scheduler = GlobalQueueScheduler()
        task = Task(hanging)
        scheduler.submit(task)

        worker = Worker(scheduler)
        worker.start()

        try:
            time.sleep(0.05)  # Let task start
            assert worker._thread.is_alive()

            # Join with timeout should return
            worker.join(timeout=0.1)
            assert worker._thread.is_alive()  # Still running
        finally:
            event.set()
            scheduler.close()
            worker.join(timeout=2.0)
        assert not worker._thread.is_alive()


class TestWorkerSchedulerIntegration:
    """Worker + Scheduler integration."""

    def test_worker_respects_closed_scheduler(self):
        """Worker exits when scheduler is closed."""
        scheduler = GlobalQueueScheduler()

        task = Task(lambda: 42)
        scheduler.submit(task)
        scheduler.close()

        worker = Worker(scheduler)
        worker.start()
        worker.join(timeout=1.0)

        # Worker should have exited
        assert not worker._thread.is_alive()
        # Task should be done
        assert task.is_done()

    def test_worker_waits_for_task(self):
        """Worker blocks waiting for a task when queue is empty."""
        scheduler = GlobalQueueScheduler()

        obtained_task = []

        # Worker blocks on empty queue
        worker = Worker(scheduler)
        worker.start()

        time.sleep(0.1)

        # Submit a task
        task = Task(lambda: 42)
        scheduler.submit(task)

        time.sleep(0.1)

        # Task should be done
        assert task.is_done()

        # Close and wait for worker
        scheduler.close()
        worker.join(timeout=1.0)

        assert not worker._thread.is_alive()
        assert worker.crash() is None

    def test_worker_drain_doesn_not_affect_running_worker(self):
        """drain() removes pending tasks but running task continues."""
        event = threading.Event()

        def slow():
            event.wait()
            return 99

        scheduler = GlobalQueueScheduler()

        task1 = Task(slow)
        task2 = Task(lambda: 2)
        task3 = Task(lambda: 3)

        scheduler.submit(task1)
        scheduler.submit(task2)
        scheduler.submit(task3)

        worker = Worker(scheduler)
        worker.start()

        time.sleep(0.1)  # Let worker claim task1

        # Drain should get task2 and task3
        drained = scheduler.drain()
        assert len(drained) == 2
        assert task1.state() == TaskState.RUNNING

        # Let task1 complete
        event.set()

        # Close and wait
        scheduler.close()
        worker.join(timeout=1.0)

        # task1 should be done
        assert task1.is_done()

        # task2 and task3 were drained, so not run
        assert task2.state() == TaskState.PENDING
        assert task3.state() == TaskState.PENDING

        assert worker.crash() is None
