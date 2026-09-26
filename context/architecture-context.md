# Architecture Context

> This document is the project's architectural source of truth for
> **intent and reasoning**. It is not evidence of implementation.
> See `progress-tracker.md` for what actually exists.

## Status legend

Every architectural statement in this document must carry one of these
tags. Untagged statements should be treated as errors in this document.

| Tag | Meaning |
|---|---|
| `CONFIRMED` | Decided and (per `progress-tracker.md`) implemented and validated |
| `DECIDED` | Decided as a direction, not yet implemented/validated |
| `PROPOSED` | Under consideration, not decided |
| `EXPERIMENTAL` | Being tried in a spike/experiment; not a commitment |
| `OPEN QUESTION` | Genuinely unresolved |
| `REJECTED` | Considered and explicitly not pursued, with reason |

As of project initialization, nothing was `CONFIRMED`. On 2026-09-26, at the
end of Phase 1 (S6), ADR-001, ADR-002 and ADR-003 were promoted to
`CONFIRMED` on the evidence listed in each entry. Everything else in this
document keeps the tag it already had; in particular the open questions in
§5 remain open.

## 1. Conceptual runtime model — `DECIDED` (direction only)

```text
M logical tasks
      ↓
Runtime / Scheduler
      ↓
N real Python threads
      ↓
Multiple CPU cores
```

- **M** logical tasks: lightweight units of work submitted by the caller.
- **Scheduler**: userspace component responsible for deciding which task
  runs on which thread, and when.
- **N** real OS threads: the actual execution resource, expected to be
  bounded (e.g. related to core count), not one-thread-per-task.
- Free-threaded CPython is what makes N > 1 threads doing CPU-bound work
  useful; this model does not target GIL-enabled builds as a first-class
  target.

This is a conceptual model, not an implemented one.

## 2. Proposed components — all `PROPOSED`

None of the following are implemented. They are candidate building blocks
identified from the conceptual model, to be validated or discarded through
experimentation.

- **Task** — representation of a logical unit of work (callable + args +
  state + result/exception slot). Open question: object, coroutine-like
  generator, or something else (§5).
- **Scheduler** — decides task→thread assignment. Open question: single
  global queue vs. per-worker queues with stealing (§5).
- **Worker** — a real OS thread that pulls tasks from the scheduler and
  executes them, reporting results/exceptions back.
- **Run queue(s)** — the data structure(s) holding runnable tasks, feeding
  workers.
- **Task handle / future** — caller-facing object to await/retrieve a
  task's result or exception.
- **Runtime** — `CONFIRMED` for Phase 1 (added 2026-09-26, implemented in
  S5, ADR-003): thin facade that owns the scheduler and workers, and
  provides `spawn` and explicit start/shutdown. Takes a required explicit
  `n_workers`.

Phase 1 refinement — see `phase-1/implementation.md` and ADR-001..003, all
`CONFIRMED` at S6 (2026-09-26) for the Phase 1 design. The lists above
remain candidates for later phases:

- The swappable seam is the **Scheduler**, not the run queue. The single
  global FIFO queue is an internal detail of the Phase 1 scheduler
  implementation; a separate run-queue type is extracted only if
  per-worker queues need it.
- Task states: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`
  (see ADR-001 for transitions). There is deliberately no waiting or
  suspended state in Phase 1.

## 3. Proposed execution flow — `PROPOSED`

1. Caller submits a task (e.g. `runtime.spawn(fn, *args)`).
2. Scheduler places the task on some queue (global or per-worker — open
   question).
3. An idle worker picks up the task and executes it.
4. Result or exception is stored and made available via the task's handle.
5. On runtime shutdown, in-flight/pending tasks are drained or cancelled
   per a documented policy. *Phase 1 (ADR-003, `CONFIRMED`): shutdown
   supports both modes — drain (default) or cancel pending; tasks already
   running always run to completion.*

This flow is a starting hypothesis for experimentation, not a spec.

## 4. Constraints — `DECIDED`

- No modification of CPython internals or the interpreter.
- Python-first: implemented as a Python library, not a C extension, at
  least for the initial exploration phase.
- Targets free-threaded CPython builds as the primary environment.
- Not attempting distributed/multi-process scheduling.

## 5. Open questions

These are genuinely unresolved and should guide early experiments rather
than early implementation of a "final" design.

Annotations dated 2026-09-26 mark where the Phase 1 plan makes a
provisional choice (`DECIDED` for Phase 1 where signed off, otherwise
`PROPOSED`) so work can proceed. A provisional choice does **not** resolve
the question: an entry leaves this list only when an experiment produces
evidence and an ADR is promoted to `CONFIRMED` (see §9).

- **Queue topology**: single global run queue vs. per-worker queues with
  work-stealing? What are the tradeoffs under free-threaded Python
  specifically (lock contention on a global queue vs. stealing overhead)?
  *Phase 1 builds the global-queue baseline (ADR-002) so the comparison
  becomes possible later. Still open.*
- **Task granularity**: what's the practical minimum task size where
  scheduling overhead doesn't dominate the work? (Needs benchmarking, not
  guessing.) *Still open; needs a general benchmark harness, deferred past
  Phase 1. `benchmarks/cpu_saturation.py` exists and its one recorded run
  is Experiment 1 in `progress-tracker.md`; it does not settle this question.*
- **Task representation**: plain object with a callable, vs. something
  coroutine/generator-based for suspension points, vs. no suspension
  support at all initially? *Phase 1 decides (ADR-001, `DECIDED`) on a
  plain callable object with no suspension support. Suspension, and a
  waiting/suspended state, remain open.*
- **Backpressure**: what happens when tasks are submitted faster than
  workers can drain them — unbounded queue, bounded with blocking submit,
  or reject? *Phase 1 uses an unbounded queue purely as a deferral
  (ADR-002); not a decision on the question. Still open.*
- **Cancellation semantics**: can a running task be cancelled mid-flight,
  or only pending tasks? *Phase 1 decides pending-only (ADR-001,
  `DECIDED`), with the design keeping the policy isolated so it can change
  (`phase-1/implementation.md` §3.7). Running-task cancellation remains
  open.*
- **Thread count policy (N)**: fixed at construction, tied to
  `os.process_cpu_count()`/similar, or dynamically adjustable?
  *Phase 1 decides (ADR-003, `DECIDED`): fixed at construction, supplied
  as a required explicit `n_workers` parameter with no CPU-derived
  default. Any default policy and dynamic adjustment remain open.*
- **Relationship to `asyncio`**: out of scope initially (see
  `project-overview.md` §7) — revisit only if a concrete need emerges.
- **Blocking tasks (added 2026-09-26)**: a task that blocks on a lock, I/O
  or another task's result holds its worker, and a pool can deadlock if all
  workers block on queued tasks. Accepted as a documented Phase 1
  limitation (`phase-1/scope.md` §3); whether and how to address it
  (suspension, dependency handling, detection) is open.

## 6. Assumptions currently being made

* **OBSERVED / SUPPORTED:** Free-threaded CPython allows independent Python
  threads to execute CPU-bound Python code in parallel across multiple CPU
  cores. However, the performance benefit is workload-dependent and is not
  guaranteed for all Python workloads. Free-threaded execution introduces
  additional overhead, and synchronization, memory contention, task
  granularity, and scheduling overhead may reduce or eliminate the benefit.

* **OPEN QUESTION:** For which CPU-bound workloads does free-threaded
  multi-threading provide a sufficiently worthwhile performance benefit to
  justify the additional overheads? This should be answered through
  reproducible benchmarking rather than assumed.

* **DECIDED HYPOTHESIS:** An initial userspace task scheduler can be built
  using existing Python threading, synchronization, and thread-safe
  communication primitives, without modifying CPython or requiring new
  interpreter primitives.

* **OPEN QUESTION:** How far a userspace scheduler can evolve beyond a
  conventional worker-pool model—particularly regarding cooperative
  suspension, task migration, preemption, and other Go-like runtime
  capabilities—without requiring additional interpreter support remains to
  be determined through experimentation.


## 7. Rejected approaches

*(none yet — this project has not reached the point of rejecting a
concrete approach. Entries will be added here as experiments conclude
negatively, with the reasoning, so they are not silently retried later.)*

## 8. Architecture Decision Log (ADR)

Append-only. Newest entries at the top. Each entry: date, status, decision,
reasoning, and (if superseding an earlier entry) what it replaces.

Format:

```text
### ADR-<number> — <short title> — <STATUS> — <date>
Decision:
Reasoning:
Supersedes: (if applicable)
```

Written at Phase 1 planning time (2026-09-26). Status history on 2026-09-26:
ADR-001 and ADR-002 `DECIDED` (signed off by the project owner); ADR-003
`PROPOSED` except its worker-count clause (`DECIDED`). At S6 all three were
promoted to `CONFIRMED` after implementation and stress validation
(`phase-1/verification.md`). Full design: `phase-1/implementation.md`.

### ADR-003 — Synchronization strategy, lifecycle and worker count — CONFIRMED — 2026-09-26
Decision:
- The Phase 1 scheduler is a double-ended queue plus a closed flag under a
  single lock with a wait/notify condition, held O(1) per operation, with
  no user code run under it.
- Each task guards its state with its own short-held lock; result/exception
  are written once before the terminal transition and before the
  completion event is set.
- Runtime lifecycle is `NEW → RUNNING → STOPPING → STOPPED`, guarded by a
  short-held lifecycle lock that is never held while joining workers.
- Shutdown closes the scheduler, optionally drains and cancels pending
  tasks (cancel mode; drain mode is the default), joins all workers, then
  performs a final sweep that cancels anything still queued, then surfaces
  any recorded worker crash. Shutdown is idempotent.
- **`DECIDED` (signed off 2026-09-26):** worker count is fixed at
  construction and supplied as a required explicit `n_workers` parameter,
  validated as an integer of at least one. There is no default derived
  from the CPU count.
- No spin loops; all waits use blocking primitives.
Reasoning:
- Rejecting `submit` after `close` must be atomic with enqueueing;
  otherwise a task can be accepted after workers have exited and stay
  `PENDING` forever. A lock-free stdlib queue cannot provide that.
- The claim-versus-cancel race needs an atomic compare-and-change of task
  state; free-threaded Python provides no GIL-atomicity safety net.
- This is a justified deviation from "prefer queues over locks"
  (`coding-standards.md` §4), not an oversight; each lock is documented
  with what it protects.
- The final sweep guarantees no handle hangs even if every worker crashed.
- A required explicit worker count avoids baking a CPU-count policy in
  before the thread-count question has been investigated, and keeps
  behavior reproducible across machines.
Evidence (added at S6, 2026-09-26): `pyron/runtime.py`, `pyron/worker.py`, `pyron/scheduler.py`; `tests/test_s4_worker.py`, `tests/test_s5_runtime.py`, `tests/test_s6_stress.py`. Exercised: both shutdown modes, idempotence, worker crash surfaced once, final sweep after every worker died, spawn racing shutdown (including tasks spawning children mid-shutdown), concurrent shutdown callers, and 20 create/load/shutdown rounds with no thread leaks. Run on free-threaded CPython 3.14.7 with the GIL disabled.
Refinements found while implementing (behavior of the code, not changes to the decision): (1) a failed `start()` (thread creation error) closes the scheduler, cancels queued tasks, joins the workers already started, and leaves the runtime `STOPPED`; (2) `shutdown()` from one of the runtime's own worker threads raises `RuntimeError` (a worker cannot join itself); (3) only the call that moves `RUNNING → STOPPING` performs the shutdown, so concurrent or repeated callers return immediately without waiting for it to finish; (4) if several workers crashed, only the first recorded crash is raised.
Supersedes: none.

### ADR-002 — Scheduler as the swappable seam; Phase 1 global FIFO queue — CONFIRMED — 2026-09-26
Decision:
- The swappable interface is a `Scheduler` protocol with `submit`,
  `next_task`, `close`, `drain`, and a shared contract (documented in
  `phase-1/implementation.md` §3.3).
- Phase 1 provides one implementation, `GlobalQueueScheduler`: single
  unbounded FIFO queue. The queue is internal to it, not a separate entity.
- `Worker` depends only on the `next_task` view; `Runtime` on
  `submit`/`close`/`drain`. The scheduler is injected into `Runtime`.
- Contract tests are parametrized over scheduler implementations.
Reasoning:
- Per-worker queues with stealing cannot be expressed as one queue
  interface, so a queue-level seam would need to be replaced later. A
  scheduler-level seam satisfies `coding-standards.md` §7 (policies behind a
  swappable interface).
- Unbounded is a deferral of the backpressure question, not an answer to it.
- Signed off "as of now" — revisit via a new ADR if evidence (for example
  from work-stealing experiments) shows the seam is in the wrong place.
Evidence (added at S6, 2026-09-26): `pyron/scheduler.py`; `tests/test_s3_scheduler.py` (contract, FIFO, atomic close/submit and drain, multi-worker no-loss/no-duplicate) and the close-vs-submit race test in `tests/test_s6_stress.py`. `Worker` and `Runtime` depend only on the `Scheduler` protocol, and `Runtime` accepts an injected scheduler (tested). No second `Scheduler` implementation exists yet, so substitutability is untested beyond the single implementation; the shared contract tests are the mechanism for that. Nothing here is a performance claim.
Supersedes: none.

### ADR-001 — Task representation and state model — CONFIRMED — 2026-09-26
Decision:
- A task is a plain object wrapping a callable and its arguments; no
  suspension support in Phase 1. Callers receive a separate `TaskHandle`,
  never the task.
- States: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`. Legal
  transitions only: `PENDING→RUNNING`, `PENDING→CANCELLED`,
  `RUNNING→COMPLETED`, `RUNNING→FAILED`. Terminal states are final.
- Cancellation applies to pending tasks only. A running task cannot be
  cancelled in Phase 1. This is a policy, not a structural limit: the legal
  transitions live in a single table, `Task.cancel` is the sole
  cancellation decision point (handle and shutdown both delegate to it),
  `cancel` is contractually a request that reports whether the task is now
  cancelled, and cancellation intent is kept separable from state, so
  cooperative running-task cancellation can be added later by changing the
  table and `Task.cancel` (and optionally passing a token via the
  invocation hook) without touching `Worker` or `Scheduler`. Design:
  `phase-1/implementation.md` §3.7.
- A `BaseException` from a task marks it `FAILED` (so waiters are released)
  and is then re-raised so the worker crashes loudly; ordinary exceptions
  mark it `FAILED` and the worker continues.
- There is no `WAITING`/`SUSPENDED` state. A blocked task remains `RUNNING`
  and holds its worker.
- The task's invocation step is a single overridable hook so a future task
  kind can change execution without changing state handling.
Reasoning:
- A waiting state with no possible transition into it would be dead;
  entering it requires cooperative suspension, which is an open question.
- `done` (the example in `coding-standards.md` §5) is split into three
  outcomes because the handle must distinguish value, error and cancelled.
- Known consequences: (1) a pool can deadlock when all workers run tasks
  blocked on queued tasks — accepted and documented, not solved; (2) adding
  suspension later needs a new state and a resubmit path on `Scheduler`,
  which changes the Worker/Scheduler contract, so it warrants its own ADR.
- Signed off "for now" (five states) on 2026-09-26; revisit through a new
  ADR entry rather than editing this one.
Evidence (added at S6, 2026-09-26): `pyron/task.py`, `pyron/handle.py`; `tests/test_s1_task.py`, `tests/test_s2_handle.py`, and the claim-vs-cancel and fetch-vs-shutdown-cancel stress tests in `tests/test_s6_stress.py`. Every accepted task ended in exactly one terminal state, and "callable ran" held exactly when the state was `COMPLETED`. Cancellation seam check: outside `pyron/task.py`, no code compares against or branches on a `TaskState` value (grep of `runtime`, `worker`, `scheduler`, `handle`); the pending-only rule lives only in the transition table and `Task.cancel`. Confirmed for a plain callable object with five states and no suspension; suspension remains open.
Supersedes: none.

## 9. How to use this document as an agent

- Never cite this document as evidence that something is implemented —
  cross-check `progress-tracker.md` and the actual code.
- When implementing a `PROPOSED` or `DECIDED` item, update its status here
  only once it's real (per `progress-tracker.md`), and only after
  validation, not merely after code compiles/runs once.
- When you resolve an open question through experimentation, move it out
  of §5 into either a new ADR entry (§8) or into §7 (Rejected approaches)
  with the reasoning.
