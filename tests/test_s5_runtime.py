"""S5 tests: Runtime — lifecycle, spawn, shutdown.

Validates:
- Construction validation of n_workers
- Lifecycle: NEW -> RUNNING -> STOPPING -> STOPPED, spawn gating
- M >> N tasks each run exactly once, on at most N distinct threads
- Both shutdown modes (drain, cancel), idempotence, context manager
- Crash paths: worker crash surfaced once; all workers dead -> final sweep
- spawn racing shutdown: every accepted task reaches a terminal state
"""

import threading
import pytest
from pyron import (
    Runtime,
    RuntimeState,
    RuntimeClosedError,
    RuntimeNotStartedError,
    TaskCancelledError,
    TaskState,
)
from pyron.scheduler import GlobalQueueScheduler

NO_THREAD_WARNING = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning"
)  # loud worker crash is the behavior under test


class Boom(BaseException):
    pass


class TestConstruction:
    def test_requires_n_workers(self):
        with pytest.raises(TypeError):
            Runtime()  # type: ignore[call-arg]

    @pytest.mark.parametrize("bad", [0, -1])
    def test_rejects_below_one(self, bad):
        with pytest.raises(ValueError):
            Runtime(bad)

    @pytest.mark.parametrize("bad", [1.5, "2", None, True])
    def test_rejects_non_int(self, bad):
        with pytest.raises(TypeError):
            Runtime(bad)  # type: ignore[arg-type]

    def test_new_state_and_n_workers(self):
        rt = Runtime(3)
        assert rt.state() is RuntimeState.NEW
        assert rt.n_workers == 3

    def test_construction_starts_no_threads(self):
        before = threading.active_count()
        Runtime(4)
        assert threading.active_count() == before


class TestLifecycle:
    def test_spawn_before_start(self):
        rt = Runtime(1)
        with pytest.raises(RuntimeNotStartedError):
            rt.spawn(lambda: 1)

    def test_start_then_shutdown_states(self):
        rt = Runtime(2)
        rt.start()
        assert rt.state() is RuntimeState.RUNNING
        rt.shutdown()
        assert rt.state() is RuntimeState.STOPPED

    def test_start_twice_raises(self):
        rt = Runtime(1)
        rt.start()
        try:
            with pytest.raises(RuntimeError):
                rt.start()
        finally:
            rt.shutdown()

    def test_start_after_stop_raises(self):
        rt = Runtime(1)
        rt.start()
        rt.shutdown()
        with pytest.raises(RuntimeError):
            rt.start()

    def test_spawn_after_shutdown(self):
        rt = Runtime(1)
        rt.start()
        rt.shutdown()
        with pytest.raises(RuntimeClosedError):
            rt.spawn(lambda: 1)

    def test_shutdown_before_start_is_noop(self):
        rt = Runtime(1)
        rt.shutdown()
        assert rt.state() is RuntimeState.NEW

    def test_shutdown_idempotent(self):
        rt = Runtime(2)
        rt.start()
        rt.shutdown()
        rt.shutdown()
        rt.shutdown(cancel_pending=True)
        assert rt.state() is RuntimeState.STOPPED

    def test_context_manager(self):
        with Runtime(2) as rt:
            assert rt.state() is RuntimeState.RUNNING
            h = rt.spawn(lambda: 42)
            assert h.result(timeout=5) == 42
        assert rt.state() is RuntimeState.STOPPED

    def test_shutdown_joins_all_workers(self):
        rt = Runtime(3)
        rt.start()
        rt.shutdown()
        assert all(not w._thread.is_alive() for w in rt._workers)


class TestSpawn:
    def test_args_and_kwargs(self):
        with Runtime(1) as rt:
            h = rt.spawn(lambda a, b=0: a + b, 2, b=3)
            assert h.result(timeout=5) == 5

    def test_exception_delivered_worker_survives(self):
        with Runtime(1) as rt:
            bad = rt.spawn(lambda: 1 / 0)
            good = rt.spawn(lambda: "ok")
            with pytest.raises(ZeroDivisionError):
                bad.result(timeout=5)
            assert bad.state() is TaskState.FAILED
            assert good.result(timeout=5) == "ok"

    def test_many_tasks_run_exactly_once_on_bounded_threads(self):
        n_workers, m = 4, 1000
        counts = [0] * m
        threads = set()
        lock = threading.Lock()

        def work(i):
            with lock:
                counts[i] += 1
                threads.add(threading.get_ident())
            return i

        with Runtime(n_workers) as rt:
            handles = [rt.spawn(work, i) for i in range(m)]
            results = [h.result(timeout=30) for h in handles]

        assert results == list(range(m))
        assert counts == [1] * m
        assert 1 <= len(threads) <= n_workers

    def test_spawn_from_multiple_threads(self):
        with Runtime(4) as rt:
            handles, hl = [], threading.Lock()

            def submitter(base):
                local = [rt.spawn(lambda x=base + i: x) for i in range(100)]
                with hl:
                    handles.extend(local)

            ts = [threading.Thread(target=submitter, args=(k * 100,)) for k in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            assert sorted(h.result(timeout=30) for h in handles) == list(range(800))


class TestShutdownModes:
    def _blocked_runtime(self, queued):
        """1 worker held by a blocking task, plus `queued` pending tasks."""
        rt = Runtime(1)
        rt.start()
        started, release = threading.Event(), threading.Event()
        ran = []

        def blocker():
            started.set()
            assert release.wait(10)
            return "blocker"

        first = rt.spawn(blocker)
        assert started.wait(5)
        pending = [rt.spawn(ran.append, i) for i in range(queued)]
        return rt, first, pending, release, ran

    def test_drain_runs_everything(self):
        rt, first, pending, release, ran = self._blocked_runtime(10)
        release.set()
        rt.shutdown()
        assert first.result(timeout=1) == "blocker"
        assert all(h.state() is TaskState.COMPLETED for h in pending)
        assert ran == list(range(10))

    def test_cancel_cancels_pending_but_running_finishes(self):
        rt, first, pending, release, ran = self._blocked_runtime(10)
        t = threading.Thread(target=rt.shutdown, kwargs={"cancel_pending": True})
        t.start()
        # Pending tasks are cancelled by shutdown before the worker is freed.
        for h in pending:
            with pytest.raises(TaskCancelledError):
                h.result(timeout=5)
        assert first.state() is TaskState.RUNNING
        release.set()
        t.join(10)
        assert not t.is_alive()
        assert first.result(timeout=1) == "blocker"
        assert ran == []
        assert rt.state() is RuntimeState.STOPPED

    def test_handle_cancelled_before_shutdown_is_skipped(self):
        rt, first, pending, release, ran = self._blocked_runtime(3)
        assert pending[1].cancel() is True
        release.set()
        rt.shutdown()
        assert ran == [0, 2]
        assert pending[1].state() is TaskState.CANCELLED

    def test_shutdown_from_worker_thread_rejected(self):
        with Runtime(1) as rt:
            h = rt.spawn(rt.shutdown)
            with pytest.raises(RuntimeError):
                h.result(timeout=5)


class TestCrashHandling:
    @NO_THREAD_WARNING
    def test_crash_surfaced_once_by_shutdown(self):
        rt = Runtime(2)
        rt.start()
        h = rt.spawn(lambda: (_ for _ in ()).throw(Boom("x")))
        with pytest.raises(Boom):
            h.result(timeout=5)  # waiters are released with FAILED
        assert h.state() is TaskState.FAILED
        # The other worker keeps serving.
        assert rt.spawn(lambda: 7).result(timeout=5) == 7
        with pytest.raises(Boom):
            rt.shutdown()
        rt.shutdown()  # second call: silent, idempotent
        assert rt.state() is RuntimeState.STOPPED

    @NO_THREAD_WARNING
    def test_all_workers_crashed_final_sweep_cancels_stranded(self):
        rt = Runtime(1)
        rt.start()
        gate = threading.Event()

        def crasher():
            assert gate.wait(10)
            raise Boom("dead")

        first = rt.spawn(crasher)
        stranded = [rt.spawn(lambda: 1) for _ in range(5)]
        gate.set()
        with pytest.raises(Boom):
            first.result(timeout=5)
        # The only worker is dead; stranded tasks sit in the queue until
        # shutdown's final sweep cancels them.
        with pytest.raises(Boom):
            rt.shutdown()
        for h in stranded:
            assert h.state() is TaskState.CANCELLED
            with pytest.raises(TaskCancelledError):
                h.result(timeout=1)

    def test_start_failure_releases_started_workers(self, monkeypatch):
        from pyron import worker as worker_mod

        real_start = worker_mod.Worker.start
        calls = {"n": 0}

        def flaky_start(self):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("can't start new thread")
            real_start(self)

        monkeypatch.setattr(worker_mod.Worker, "start", flaky_start)
        rt = Runtime(4)
        before = threading.active_count()
        with pytest.raises(RuntimeError, match="can't start"):
            rt.start()
        assert rt.state() is RuntimeState.STOPPED
        assert threading.active_count() == before


class TestSpawnShutdownRace:
    @pytest.mark.stress
    @pytest.mark.parametrize("cancel", [False, True])
    def test_every_accepted_task_reaches_terminal_state(self, cancel):
        for _ in range(30):
            rt = Runtime(3)
            rt.start()
            accepted, al = [], threading.Lock()
            stop = threading.Event()

            def spammer():
                while not stop.is_set():
                    try:
                        h = rt.spawn(lambda: 1)
                    except RuntimeClosedError:
                        return
                    with al:
                        accepted.append(h)

            ts = [threading.Thread(target=spammer) for _ in range(4)]
            for t in ts:
                t.start()
            rt.shutdown(cancel_pending=cancel)
            stop.set()
            for t in ts:
                t.join(10)
                assert not t.is_alive()
            assert accepted
            for h in accepted:
                assert h.done(), h.state()
                assert h.state() in (TaskState.COMPLETED, TaskState.CANCELLED)


class TestCustomScheduler:
    def test_injected_scheduler_is_used(self):
        sched = GlobalQueueScheduler()
        with Runtime(2, scheduler=sched) as rt:
            assert rt._scheduler is sched
            assert rt.spawn(lambda: 3).result(timeout=5) == 3
