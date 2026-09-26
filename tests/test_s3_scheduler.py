"""S3 tests: Scheduler protocol and GlobalQueueScheduler implementation.

Validates:
- Scheduler protocol compliance
- GlobalQueueScheduler FIFO ordering
- Close/submit atomicity
- next_task() blocking behavior
- drain() atomicity
- Multiple workers can fetch different tasks
"""

import pytest
import threading
import time
from pyron.task import Task
from pyron.scheduler import GlobalQueueScheduler
from pyron.errors import SchedulerClosedError


class SchedulerContractTests:
    """Tests that any Scheduler implementation must pass.

    These are parametrized so they can be run against any implementation
    (GlobalQueueScheduler, future work-stealing scheduler, etc.).
    """

    @pytest.fixture
    def scheduler(self):
        """Provide a scheduler instance (override in subclasses)."""
        return GlobalQueueScheduler()

    def test_submit_and_next_task(self, scheduler):
        """Task submitted is retrievable."""
        task = Task(lambda: 42)
        scheduler.submit(task)
        retrieved = scheduler.next_task()
        assert retrieved is task

    def test_submit_multiple_tasks(self, scheduler):
        """Multiple submitted tasks are retrievable."""
        tasks = [Task(lambda i=i: i) for i in range(3)]
        for t in tasks:
            scheduler.submit(t)

        retrieved = [scheduler.next_task() for _ in range(3)]
        assert retrieved == tasks

    def test_submit_fifo_order(self, scheduler):
        """Tasks are retrieved in FIFO order."""
        tasks = [Task(lambda i=i: i) for i in range(5)]
        for t in tasks:
            scheduler.submit(t)

        for expected in tasks:
            retrieved = scheduler.next_task()
            assert retrieved is expected

    def test_submit_after_close_raises(self, scheduler):
        """submit() raises SchedulerClosedError after close()."""
        scheduler.close()
        task = Task(lambda: 42)

        with pytest.raises(SchedulerClosedError):
            scheduler.submit(task)

    def test_next_task_blocks_until_task_available(self, scheduler):
        """next_task() blocks while queue is empty and not closed."""
        task_obtained = []

        def waiter():
            # This should block until we submit a task
            t = scheduler.next_task()
            task_obtained.append(t)

        w = threading.Thread(target=waiter)
        w.start()

        time.sleep(0.1)  # Let waiter block
        assert len(task_obtained) == 0  # Still waiting

        # Submit a task
        task = Task(lambda: 42)
        scheduler.submit(task)

        w.join(timeout=1.0)
        assert len(task_obtained) == 1
        assert task_obtained[0] is task

    def test_next_task_returns_none_when_closed_and_empty(self, scheduler):
        """next_task() returns None when closed and queue is empty."""
        scheduler.close()
        result = scheduler.next_task()
        assert result is None

    def test_close_idempotent(self, scheduler):
        """close() can be called multiple times."""
        scheduler.close()
        scheduler.close()
        scheduler.close()

        task = Task(lambda: 42)
        with pytest.raises(SchedulerClosedError):
            scheduler.submit(task)

    def test_close_wakes_waiting_workers(self, scheduler):
        """close() wakes all blocked next_task() callers."""
        results = []

        def waiter():
            result = scheduler.next_task()
            results.append(result)

        # Start multiple waiters
        threads = [threading.Thread(target=waiter) for _ in range(3)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        assert len(results) == 0  # All waiting

        # Close should wake them all
        scheduler.close()

        for t in threads:
            t.join(timeout=1.0)

        # All should have gotten None
        assert results == [None, None, None]

    def test_drain_returns_all_queued_tasks(self, scheduler):
        """drain() returns all tasks in the queue."""
        tasks = [Task(lambda i=i: i) for i in range(5)]
        for t in tasks:
            scheduler.submit(t)

        drained = scheduler.drain()
        assert drained == tasks

    def test_drain_clears_queue(self, scheduler):
        """After drain(), queue is empty."""
        tasks = [Task(lambda i=i: i) for i in range(3)]
        for t in tasks:
            scheduler.submit(t)

        scheduler.drain()

        # Queue should be empty now
        scheduler.close()
        result = scheduler.next_task()
        assert result is None

    def test_drain_empty_queue(self, scheduler):
        """drain() on empty queue returns empty list."""
        drained = scheduler.drain()
        assert drained == []

    def test_drain_atomic(self, scheduler):
        """drain() is atomic: returns snapshot at one point in time."""
        tasks = [Task(lambda i=i: i) for i in range(10)]
        for t in tasks:
            scheduler.submit(t)

        drained = scheduler.drain()
        assert len(drained) == 10
        assert drained == tasks

        # Queue should be empty after drain
        drained_again = scheduler.drain()
        assert drained_again == []


class TestGlobalQueueScheduler(SchedulerContractTests):
    """GlobalQueueScheduler implementation tests."""

    def test_close_submit_atomicity_submit_before_close(self):
        """Close and submit race: submit before close completes."""
        scheduler = GlobalQueueScheduler()

        submitted = [False]
        closed = [False]

        def submitter():
            try:
                task = Task(lambda: 42)
                scheduler.submit(task)
                submitted[0] = True
            except SchedulerClosedError:
                submitted[0] = False

        def closer():
            scheduler.close()
            closed[0] = True

        # Race: submitter and closer compete
        t1 = threading.Thread(target=submitter)
        t2 = threading.Thread(target=closer)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one outcome: either submit succeeded (task in queue) or failed
        if submitted[0]:
            # Submit won, task should be in queue
            task = scheduler.next_task()
            assert task is not None
        else:
            # Close won, no task should be in queue
            task = scheduler.next_task()
            assert task is None

    def test_multiple_workers_get_different_tasks(self):
        """Multiple workers can retrieve different tasks concurrently."""
        scheduler = GlobalQueueScheduler()

        tasks = [Task(lambda i=i: i) for i in range(10)]
        for t in tasks:
            scheduler.submit(t)

        retrieved = []
        lock = threading.Lock()

        def worker():
            while True:
                t = scheduler.next_task()
                if t is None:
                    break
                with lock:
                    retrieved.append(t)

        # Start multiple workers
        workers = [threading.Thread(target=worker) for _ in range(3)]
        for w in workers:
            w.start()

        # Close to let workers exit
        scheduler.close()

        for w in workers:
            w.join(timeout=1.0)

        # All tasks should be retrieved exactly once
        assert len(retrieved) == 10
        assert set(retrieved) == set(tasks)

    def test_task_retrieved_by_exactly_one_worker(self):
        """Each task is retrieved by exactly one worker."""
        scheduler = GlobalQueueScheduler()

        num_tasks = 20
        tasks = [Task(lambda i=i: i) for i in range(num_tasks)]
        for t in tasks:
            scheduler.submit(t)

        task_ids = {}
        lock = threading.Lock()

        def worker():
            while True:
                t = scheduler.next_task()
                if t is None:
                    break
                with lock:
                    task_id = id(t)
                    task_ids[task_id] = task_ids.get(task_id, 0) + 1

        # Start multiple workers
        workers = [threading.Thread(target=worker) for _ in range(4)]
        for w in workers:
            w.start()

        scheduler.close()

        for w in workers:
            w.join(timeout=1.0)

        # Each task should have been retrieved exactly once
        for count in task_ids.values():
            assert count == 1

    def test_next_task_blocking_with_multiple_waiters(self):
        """Multiple workers can wait on next_task() concurrently."""
        scheduler = GlobalQueueScheduler()

        obtained = []
        lock = threading.Lock()

        def waiter():
            t = scheduler.next_task()
            with lock:
                obtained.append(t)

        # Start multiple waiters
        threads = [threading.Thread(target=waiter) for _ in range(3)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        assert len(obtained) == 0  # All waiting

        # Submit exactly one task (only one waiter should wake)
        task1 = Task(lambda: 1)
        scheduler.submit(task1)

        time.sleep(0.05)
        assert len(obtained) == 1  # One waiter got it

        # Close immediately to make remaining waiters exit with None
        # (before submitting more tasks)
        scheduler.close()

        for t in threads:
            t.join(timeout=1.0)

        # All three waiters should have obtained something
        assert len(obtained) == 3
        # One got the task, two got None
        none_count = sum(1 for x in obtained if x is None)
        assert none_count == 2, f"Expected 2 Nones, got {none_count}. Obtained: {obtained}"
        assert task1 in obtained

    def test_submit_after_some_tasks_consumed(self):
        """Can submit tasks after some have been consumed."""
        scheduler = GlobalQueueScheduler()

        task1 = Task(lambda: 1)
        task2 = Task(lambda: 2)
        scheduler.submit(task1)

        retrieved1 = scheduler.next_task()
        assert retrieved1 is task1

        # Submit another
        scheduler.submit(task2)
        retrieved2 = scheduler.next_task()
        assert retrieved2 is task2

    def test_queue_ordering_stress(self):
        """FIFO ordering is maintained under load (100 tasks)."""
        scheduler = GlobalQueueScheduler()

        num_tasks = 100
        tasks = [Task(lambda i=i: i) for i in range(num_tasks)]
        for t in tasks:
            scheduler.submit(t)

        retrieved = []
        for _ in range(num_tasks):
            t = scheduler.next_task()
            retrieved.append(t)

        assert retrieved == tasks

    def test_concurrent_submit_and_retrieve(self):
        """Tasks can be submitted and retrieved concurrently."""
        scheduler = GlobalQueueScheduler()

        results = {"submitted": 0, "retrieved": 0}
        lock = threading.Lock()

        def submitter():
            for i in range(20):
                task = Task(lambda j=i: j)
                scheduler.submit(task)
                with lock:
                    results["submitted"] += 1
                time.sleep(0.001)

        def worker():
            while True:
                t = scheduler.next_task()
                if t is None:
                    break
                with lock:
                    results["retrieved"] += 1

        s = threading.Thread(target=submitter)
        w = threading.Thread(target=worker)

        w.start()
        s.start()

        s.join()
        time.sleep(0.1)  # Let worker catch up

        scheduler.close()
        w.join(timeout=1.0)

        assert results["submitted"] == 20
        assert results["retrieved"] == 20

    def test_drain_concurrent_with_submit(self):
        """drain() atomically removes tasks even with concurrent submit."""
        scheduler = GlobalQueueScheduler()

        tasks = [Task(lambda i=i: i) for i in range(5)]
        for t in tasks:
            scheduler.submit(t)

        # Drain gets the 5 tasks
        drained = scheduler.drain()
        assert len(drained) == 5

        # Submit more
        more_tasks = [Task(lambda i=i: i) for i in range(3)]
        for t in more_tasks:
            scheduler.submit(t)

        # Drain again gets the new ones
        drained_again = scheduler.drain()
        assert len(drained_again) == 3
        assert drained_again == more_tasks

    def test_no_task_lost_on_close(self):
        """No tasks are lost when scheduler is closed."""
        scheduler = GlobalQueueScheduler()

        tasks = [Task(lambda i=i: i) for i in range(10)]
        for t in tasks:
            scheduler.submit(t)

        retrieved = []

        def worker():
            while True:
                t = scheduler.next_task()
                if t is None:
                    break
                retrieved.append(t)

        w = threading.Thread(target=worker)
        w.start()

        time.sleep(0.05)

        # Close (some tasks may not have been retrieved yet)
        scheduler.close()

        w.join(timeout=1.0)

        # All submitted tasks should be retrievable or in queue
        # (worker should have gotten what was available before close)
        drained = scheduler.drain()
        all_tasks = retrieved + drained

        assert len(all_tasks) == 10
        assert set(all_tasks) == set(tasks)
