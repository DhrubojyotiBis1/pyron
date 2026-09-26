"""S6 tests: stress, race hardening, and the recorded deadlock limitation.

Each test probes one race named in phase-1/verification.md §5:
- claim vs cancel (many cancellers against running workers)
- close vs submit (scheduler level)
- fetch vs shutdown-cancel (workers fetching while shutdown drains)
- spawn from inside tasks racing shutdown
- concurrent shutdown callers
- soak: repeated create / load / shutdown, no thread leaks
- documented limitation: blocked tasks can starve the pool

Invariant checked everywhere: every accepted task ends in exactly one
terminal state, and "ran" (callable executed) <=> COMPLETED.
"""

import random
import threading
import time
import pytest
from pyron import Runtime, RuntimeState, RuntimeClosedError, TaskState
from pyron.errors import SchedulerClosedError
from pyron.scheduler import GlobalQueueScheduler
from pyron.task import Task

pytestmark = pytest.mark.stress


def _join_all(threads, timeout=20):
    for t in threads:
        t.join(timeout)
        assert not t.is_alive(), "helper thread hung"


class TestClaimVsCancel:
    def test_exactly_one_of_ran_or_cancelled(self):
        for _ in range(10):
            m = 2000
            ran = [0] * m
            with Runtime(4) as rt:
                handles = [rt.spawn(ran.__setitem__, i, 1) for i in range(m)]
                cancelled = [False] * m

                def canceller(seed):
                    order = list(range(m))
                    random.Random(seed).shuffle(order)
                    for i in order:
                        if handles[i].cancel():
                            cancelled[i] = True  # only this winner could set it

                cs = [threading.Thread(target=canceller, args=(s,)) for s in range(4)]
                for t in cs:
                    t.start()
                _join_all(cs)
            for i, h in enumerate(handles):
                assert h.done()
                if h.state() is TaskState.CANCELLED:
                    assert ran[i] == 0
                else:
                    assert h.state() is TaskState.COMPLETED
                    assert ran[i] == 1
                    assert not cancelled[i]


class TestCloseVsSubmit:
    def test_no_task_stranded_by_close_race(self):
        for _ in range(300):
            sched = GlobalQueueScheduler()
            accepted, lock = [], threading.Lock()
            go = threading.Barrier(5)

            def submitter():
                go.wait()
                for _ in range(50):
                    t = Task(lambda: None)
                    try:
                        sched.submit(t)
                    except SchedulerClosedError:
                        return
                    with lock:
                        accepted.append(t)

            ts = [threading.Thread(target=submitter) for _ in range(4)]
            for t in ts:
                t.start()
            go.wait()
            sched.close()
            _join_all(ts)

            seen = []
            while (t := sched.next_task()) is not None:
                seen.append(t)
            # Every accepted task is delivered exactly once; none after close.
            assert sorted(map(id, seen)) == sorted(map(id, accepted))
            with pytest.raises(SchedulerClosedError):
                sched.submit(Task(lambda: None))


class TestFetchVsShutdownCancel:
    def test_each_task_runs_or_is_cancelled_never_both(self):
        for _ in range(50):
            m = 1000
            counts = [0] * m
            lock = threading.Lock()

            def work(i):
                with lock:
                    counts[i] += 1

            rt = Runtime(4)
            rt.start()
            handles = [rt.spawn(work, i) for i in range(m)]
            rt.shutdown(cancel_pending=True)

            assert rt.state() is RuntimeState.STOPPED
            for i, h in enumerate(handles):
                assert h.done()
                if h.state() is TaskState.COMPLETED:
                    assert counts[i] == 1
                else:
                    assert h.state() is TaskState.CANCELLED
                    assert counts[i] == 0

    def test_concurrent_cancel_shutdown_and_handle_cancel(self):
        for _ in range(30):
            m = 500
            counts = [0] * m
            rt = Runtime(3)
            rt.start()
            handles = [rt.spawn(counts.__setitem__, i, 1) for i in range(m)]
            t = threading.Thread(
                target=lambda: [h.cancel() for h in reversed(handles)]
            )
            t.start()
            rt.shutdown(cancel_pending=True)
            _join_all([t])
            for i, h in enumerate(handles):
                assert h.done()
                assert (h.state() is TaskState.COMPLETED) == (counts[i] == 1)


class TestSpawnDuringShutdown:
    @pytest.mark.parametrize("cancel", [False, True])
    def test_tasks_spawning_children_while_shutting_down(self, cancel):
        for _ in range(30):
            rt = Runtime(3)
            rt.start()
            children, lock = [], threading.Lock()

            def parent():
                for _ in range(20):
                    try:
                        h = rt.spawn(lambda: 1)
                    except RuntimeClosedError:
                        return
                    with lock:
                        children.append(h)

            parents = [rt.spawn(parent) for _ in range(200)]
            rt.shutdown(cancel_pending=cancel)
            for h in parents + children:
                assert h.done(), h.state()
                assert h.state() in (TaskState.COMPLETED, TaskState.CANCELLED)


class TestConcurrentShutdown:
    def test_many_shutdown_callers_at_once(self):
        for _ in range(50):
            rt = Runtime(4)
            rt.start()
            handles = [rt.spawn(lambda: 1) for _ in range(100)]
            errors = []
            go = threading.Barrier(6)

            def stopper(cancel):
                go.wait()
                try:
                    rt.shutdown(cancel_pending=cancel)
                except BaseException as e:  # noqa: BLE001 - recorded, asserted empty
                    errors.append(e)

            ts = [threading.Thread(target=stopper, args=(i % 2 == 0,)) for i in range(6)]
            for t in ts:
                t.start()
            _join_all(ts)
            assert errors == []
            # Non-performing callers return early; the performing caller may
            # still be finishing, so wait (bounded) for STOPPED before asserting.
            deadline = time.monotonic() + 20
            while rt.state() is not RuntimeState.STOPPED:
                assert time.monotonic() < deadline, "shutdown never finished"
                time.sleep(0.001)
            for w in rt._workers:
                assert not w._thread.is_alive()
            assert all(h.done() for h in handles)


class TestSoak:
    def test_repeated_runtime_lifecycles_no_leaks(self):
        baseline = threading.active_count()
        total = 0
        for round_ in range(20):
            m = 3000
            done = [0] * m
            with Runtime(8) as rt:
                handles = []
                lock = threading.Lock()

                def submitter(base):
                    local = [rt.spawn(done.__setitem__, base + i, 1) for i in range(m // 4)]
                    with lock:
                        handles.extend(local)

                ts = [threading.Thread(target=submitter, args=(k * (m // 4),)) for k in range(4)]
                for t in ts:
                    t.start()
                _join_all(ts)
            assert all(h.state() is TaskState.COMPLETED for h in handles)
            assert done == [1] * m
            total += m
            assert threading.active_count() == baseline, f"leak in round {round_}"
        assert total == 60000


class TestDocumentedLimitation:
    """scope.md §3.2: tasks that block on queued tasks starve the pool.

    Recorded, not fixed. Bounded by handle timeouts so the test cannot hang.
    """

    def test_blocked_parents_starve_children_until_released(self):
        n = 2
        children_ran = []
        outcomes = []  # (result, children that had run at that moment)
        lock = threading.Lock()
        all_running = threading.Barrier(n)

        with Runtime(n) as rt:
            def child():
                with lock:
                    children_ran.append(1)

            def parent():
                # Ensure every worker is occupied before any child exists.
                all_running.wait(10)
                h = rt.spawn(child)  # queued behind the other blocked parents
                try:
                    h.result(timeout=1.0)
                    r = "ok"
                except TimeoutError:
                    r = "starved"
                with lock:
                    outcomes.append((r, len(children_ran)))

            # Exactly N parents occupy every worker; each waits on a queued child.
            parents = [rt.spawn(parent) for _ in range(n)]
            for p in parents:
                p.result(timeout=10)

            # The first wait to end did so by timeout, with no child having
            # run: every worker was held by a blocked task (deadlock shape,
            # broken here only by the timeout).
            assert outcomes[0] == ("starved", 0)
            # After the parents finish, the pool recovers and drains children.
            rt.shutdown()
            assert len(children_ran) == n
