# Phase 1 — Scope

> Status: IMPLEMENTED (limitations below verified or recorded at S6). Last updated: 2026-09-26.
> Scope changes for this phase must be flagged and recorded here, not
> absorbed silently (`ai-workflow-rules.md` §2).

## 1. In scope

- M logical tasks, N worker threads (N is a required explicit
  `n_workers` argument, fixed for the runtime's lifetime), exactly **one
  global FIFO queue**.
- Minimal entities: `Task`, `TaskState`, `TaskHandle`, `Scheduler`
  (protocol), `GlobalQueueScheduler`, `Worker`, `Runtime`.
- A defined task state machine: `PENDING`, `RUNNING`, `COMPLETED`,
  `FAILED`, `CANCELLED`.
- `spawn(fn, *args, **kwargs)` returning a handle; result / exception
  retrieval with optional timeout.
- Cancellation of **pending** tasks only.
- Explicit runtime lifecycle: start, shutdown, context-manager use.
- Two documented shutdown modes: drain pending work, or cancel pending work.
- Exceptions raised inside tasks captured and surfaced through the handle.
- Loud failure for infrastructure errors (worker/scheduler bugs) rather than
  silent degradation.
- Correctness tests, race tests and repeated stress tests on a free-threaded
  build.
- Documentation of state ownership and synchronization for every component.

## 2. Out of scope

| Item | Why | Where it is tracked |
|---|---|---|
| Work-stealing / per-worker queues | Phase 1 is the baseline to compare against; needs validated basics first | `architecture-context.md` §5 (queue topology) |
| Benchmarks and any performance claim | No benchmark harness exists; claims require committed reproducible benchmarks | `ai-workflow-rules.md` §8; future phase |
| Cancelling a `RUNNING` task | Semantics unresolved; needs cooperative checkpoints | `architecture-context.md` §5 (cancellation) |
| Task suspension / a `WAITING` or `SUSPENDED` state | Requires cooperative suspension (generator/coroutine-style tasks); would change the Worker/Scheduler contract | `architecture-context.md` §5 (task representation) |
| Backpressure (bounded queue, blocking or rejecting submit) | Unresolved; queue is unbounded in this phase | `architecture-context.md` §5 (backpressure) |
| Task dependencies / DAGs | Would live above the scheduler as its own feature | Not queued |
| Priorities, fairness, time slicing, preemption | Not needed to validate the basic flow | Not queued |
| Dynamic worker count / autoscaling | Fixed at construction | `architecture-context.md` §5 (thread count) |
| `asyncio` integration | Out of project scope initially | `project-overview.md` §7 |
| Multi-process / distributed scheduling | Project non-goal | `project-overview.md` §7 |
| C extensions / CPython modification | Project constraint | `architecture-context.md` §4 |
| Packaging, CI, formatter/linter choice | Not needed yet; record choices in tracker when made | `coding-standards.md` §12 |

## 3. Known limitations of the Phase 1 design

These are accepted consequences of the design, not bugs to fix in this
phase. Each is to be stated in the relevant docstring or ADR.

1. **Blocked tasks hold their worker.** A task is a plain callable. If it
   waits on a lock, I/O, sleep, or another task's result, it does so on its
   worker thread and stays `RUNNING`; the runtime cannot see or interrupt
   the wait. There is deliberately no `WAITING` state, because nothing could
   transition into it.
2. **The pool can deadlock.** If all N workers run tasks that block waiting
   for the result of tasks still queued behind them (e.g. a task that
   spawns children and waits on their handles), no task can make progress.
   Phase 1 does not detect or prevent this. One test demonstrates it with a
   timeout so the behavior is recorded.
3. **No cancellation once running.** A task claimed by a worker runs to
   completion or failure. Cancelling it has no effect (returns "not
   cancelled"). This is a Phase 1 policy, not a permanent rule: the design
   isolates it behind a single transition table and one cancel entry point
   so it can change later (`implementation.md` §3.7).
4. **Unbounded queue.** Tasks submitted faster than they drain accumulate
   without limit; memory is the only bound.
5. **Single-lock global queue.** Every submit and every worker fetch takes
   the same scheduler lock. Contention is expected to matter as N grows;
   this is a hypothesis to be measured later, not a measured fact.
6. **FIFO only.** No priorities or fairness guarantees beyond queue order;
   completion order is not submission order.
7. **Worker crash is not recovered.** A worker that dies from an
   infrastructure error or a `BaseException` in a task is not restarted.
   The crash is recorded and surfaced loudly at shutdown; remaining workers
   continue, and a final sweep at shutdown cancels anything left pending.
8. **Requires a free-threaded build to be meaningful.** Correctness tests
   also run on other builds, but the phase's purpose (parallel CPU-bound
   execution) is only observable with the GIL disabled.
9. **No task timeouts.** `result(timeout)` bounds the *wait*, not the task's
   execution; a slow task still occupies its worker.
10. **Retained references.** A failed task's stored exception holds its
    traceback (and frames) until the handle is released.
11. **Spawning from inside a task is permitted but unguarded.** It is the
    entry route to limitation 2.

## 4. Scope-change rule

If implementation reveals that something out of scope is needed (for
example, deadlock handling turns out to be unavoidable for a test), stop,
record it under "Blocked / unresolved" in `../progress-tracker.md`, and
propose a scoped follow-up rather than expanding this phase.
