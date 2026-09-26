# Pyron

An experimental, Go-inspired **M:N concurrency runtime for free-threaded
Python**: many lightweight logical tasks scheduled onto a small, fixed pool of
real OS threads.

> **Status: experimental, Phase 1.** A minimal scheduler (one global queue,
> N workers) is implemented and tested. It is a research project, **not
> production-ready**, and makes **no performance claims** — no benchmark
> harness exists yet.

## Why

Free-threaded CPython (PEP 703, the no-GIL build) lets several threads run
Python code in parallel. Pyron explores the model Go popularised: you submit
as many tasks as you like (M), and a bounded set of worker threads (N) runs
them, instead of one thread per task.

```text
M logical tasks  →  Runtime / Scheduler  →  N real threads  →  multiple cores
```

## Requirements

- Python 3.13 or newer, ideally a **free-threaded build** (`python3.14t`,
  built with the GIL disabled). Pyron is designed and tested for that build.
  On a GIL-enabled interpreter it still runs, but threads will not execute
  Python code in parallel, so it targets the wrong environment.
- No runtime dependencies (standard library only).

Check what you have:

```bash
python -c "import sys; print(sys._is_gil_enabled())"   # want: False
```

## Install

Pyron is not published to PyPI yet. Install from a clone:

```bash
git clone https://github.com/DhrubojyotiBis1/pyron.git
cd pyron
python3.14t -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

```python
from pyron import Runtime

with Runtime(n_workers=4) as rt:
    handle = rt.spawn(pow, 2, 10)      # run pow(2, 10) on a worker
    print(handle.result())             # 1024
```

`n_workers` is **required**; there is deliberately no default derived from
the CPU count. Leaving the `with` block shuts the runtime down and waits for
queued tasks to finish.

### Many tasks, few threads

```python
from pyron import Runtime

def square(x):
    return x * x

with Runtime(n_workers=4) as rt:
    handles = [rt.spawn(square, i) for i in range(1000)]   # 1000 tasks, 4 threads
    total = sum(h.result() for h in handles)

print(total)   # 332833500
```

### Errors stay with the task

An ordinary exception marks that task `FAILED`, is re-raised when you ask for
its result, and does not affect the worker or other tasks.

```python
from pyron import Runtime, TaskState

with Runtime(n_workers=2) as rt:
    bad = rt.spawn(lambda: 1 / 0)
    good = rt.spawn(lambda: "still fine")

    try:
        bad.result()
    except ZeroDivisionError:
        print("caught:", bad.state())          # TaskState.FAILED

    print(good.result())                       # still fine
    print(bad.exception())                     # division by zero
```

### Timeouts and cancellation

```python
import threading
from pyron import Runtime, TaskCancelledError

release = threading.Event()

with Runtime(n_workers=1) as rt:
    rt.spawn(release.wait)                 # occupies the only worker
    queued = rt.spawn(print, "never runs")

    print(queued.cancel())                 # True: it was still pending
    try:
        queued.result()
    except TaskCancelledError:
        print("cancelled")

    slow = rt.spawn(release.wait)
    try:
        slow.result(timeout=0.1)
    except TimeoutError:
        print("gave up waiting")

    release.set()                          # let the worker finish
```

### Explicit lifecycle

The context manager is a convenience; you can drive the lifecycle yourself.

```python
from pyron import Runtime

rt = Runtime(n_workers=4)
rt.start()
try:
    h = rt.spawn(sum, range(100))
    print(h.result())                      # 4950
finally:
    rt.shutdown()                          # drain: run everything already queued
```

`rt.shutdown(cancel_pending=True)` instead cancels tasks no worker has started
yet. Tasks already running always finish.

## What it can do

| Capability | Behaviour |
|---|---|
| Fixed worker pool | `Runtime(n_workers=N)` starts exactly N non-daemon threads on `start()`. Fixed for the runtime's lifetime. |
| `spawn(fn, *args, **kwargs)` | Queues a call and returns a `TaskHandle` immediately. Safe to call from any thread, including from inside tasks. |
| Task handle | `state()`, `done()`, `result(timeout=)`, `exception(timeout=)`, `cancel()`. Multiple threads may wait on the same handle. |
| Task states | `PENDING → RUNNING → COMPLETED` or `FAILED`; `PENDING → CANCELLED`. Every task ends in exactly one terminal state. |
| FIFO scheduling | One global unbounded FIFO queue behind a `Scheduler` protocol. |
| Two shutdown modes | Drain (default) or cancel-pending. Shutdown is idempotent. |
| No lost or duplicated work | Each accepted task runs at most once and is always resolved (run or cancelled) once `shutdown()` returns. |
| Loud failure | A `BaseException` (`KeyboardInterrupt`, `SystemExit`, ...) from a task marks it `FAILED`, crashes that worker visibly, and is re-raised by `shutdown()`. |
| Lifecycle errors | `spawn` before `start` raises `RuntimeNotStartedError`; after shutdown begins it raises `RuntimeClosedError`. |
| Swappable scheduler | `Runtime(n, scheduler=...)` accepts any object implementing the `Scheduler` protocol (`submit`, `next_task`, `close`, `drain`). |

## API reference

Everything below is importable from `pyron`.

### `Runtime(n_workers, scheduler=None)`

`n_workers` must be an `int` of at least 1 (`TypeError` / `ValueError`
otherwise). States: `NEW → RUNNING → STOPPING → STOPPED`.

| Method | Description |
|---|---|
| `start()` | Start the workers. Only valid once, from `NEW`. |
| `spawn(fn, *args, **kwargs)` | Submit a task, get a `TaskHandle`. |
| `shutdown(cancel_pending=False)` | Close the queue, optionally cancel unstarted tasks, join all workers, then raise the first recorded worker crash, if any. |
| `state()` | Current `RuntimeState`. |
| `n_workers` | The configured worker count. |
| `with Runtime(n) as rt:` | `start()` on entry, drain-mode `shutdown()` on exit. |

### `TaskHandle`

| Method | Description |
|---|---|
| `state()` | Current `TaskState` (a snapshot; it may change immediately). |
| `done()` | `True` once `COMPLETED`, `FAILED` or `CANCELLED`. |
| `result(timeout=None)` | The return value. Raises the task's exception if it failed, `TaskCancelledError` if cancelled, `TimeoutError` if the wait times out. |
| `exception(timeout=None)` | The task's exception, or `None` if it completed. Same cancel/timeout errors. |
| `cancel()` | `True` if the task is now cancelled, `False` if it could not be. Treat it as a request: rely on the return value, not on which states are cancellable. |

### Also exported

`RuntimeState`, `TaskState`, `RuntimeClosedError`, `RuntimeNotStartedError`,
`TaskCancelledError`.

## Limitations

These are known and accepted for Phase 1, not bugs:

- **A blocked task holds its worker.** A task that waits on a lock, I/O,
  `sleep`, or another task's result stays `RUNNING` on its thread. There is no
  suspension or `WAITING` state.
- **The pool can deadlock.** If all N workers run tasks that wait for results of
  tasks still queued behind them (for example a task that spawns children and
  blocks on their handles), nothing can make progress. Pyron does not detect or
  prevent this. Keep task graphs shallow, or give the pool more workers than the
  deepest chain of waiting tasks.
- **Only pending tasks can be cancelled.** A running task cannot be interrupted.
- **Unbounded queue.** Submitting faster than workers drain grows memory without
  limit; there is no backpressure.
- **FIFO only.** No priorities or fairness beyond queue order.
- **Single-lock global queue.** Every submit and fetch takes one lock. Whether
  that becomes a bottleneck as N grows is an open, unmeasured question.
- **`shutdown()` cannot be called from a worker thread** (it raises
  `RuntimeError`). A second or concurrent `shutdown()` returns immediately
  without waiting for the first to finish.
- **Only tested on macOS with CPython 3.14.7 free-threaded**, for runs lasting
  seconds.

## Development

```bash
pytest            # full suite, including the stress tests
pytest -m stress  # only the stress tests
```

The suite asserts that the GIL is disabled and fails on a GIL-enabled
interpreter. Each test has a 30 s timeout so a hang fails instead of blocking.

Layout:

| Module | Contents |
|---|---|
| `pyron/task.py` | `TaskState` and `Task`, the guarded state machine |
| `pyron/handle.py` | `TaskHandle`, the caller-facing view |
| `pyron/scheduler.py` | `Scheduler` protocol and `GlobalQueueScheduler` |
| `pyron/worker.py` | `Worker`, one OS thread running tasks |
| `pyron/runtime.py` | `Runtime`, lifecycle, spawn, shutdown |
| `pyron/errors.py` | Error types |

Design and project state live in [`context/`](context/):
[`progress-tracker.md`](context/progress-tracker.md) is the source of truth for
what exists, and [`architecture-context.md`](context/architecture-context.md)
holds the design decisions (ADR-001 to ADR-003, confirmed for Phase 1) and the
open questions.

## What is deliberately not here

Pyron does not modify CPython, replace `asyncio`, or schedule across processes
or machines. Work-stealing, suspension, backpressure and a benchmark harness are
deferred beyond Phase 1.

## License

MIT. See [LICENSE](LICENSE).
