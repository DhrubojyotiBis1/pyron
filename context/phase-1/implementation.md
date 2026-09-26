# Phase 1 — Implementation Design

> Status: implemented (S0–S6); the code in `pyron/` follows this design.
> Last updated: 2026-09-26. ADR-001..003 are `CONFIRMED` (S6).
> This is a low-level design. Evidence of implementation is in the code,
> tests and `../progress-tracker.md`, not in this document.
> Rationale for the decisions lives in the ADRs (`../architecture-context.md`
> §8): ADR-001 (task model), ADR-002 (scheduler seam), ADR-003
> (synchronization and lifecycle).

## 1. Entities

| Entity | Kind | Responsibility | Owns |
|---|---|---|---|
| `TaskState` | enum | Vocabulary of the task lifecycle | nothing |
| `Task` | class (internal) | A logical unit of work: callable, arguments, guarded state machine, outcome slot | state, result / exception, completion event |
| `TaskHandle` | class (public) | Caller-facing view of one task | nothing (holds a `Task`) |
| `Scheduler` | protocol | The swappable seam: accept tasks, hand tasks to workers, close, drain | nothing |
| `GlobalQueueScheduler` | class | Phase 1 `Scheduler`: one FIFO queue | the queue and its closed flag |
| `Worker` | class | One OS thread that repeatedly fetches and runs tasks | its thread, crash record |
| `Runtime` | class (public) | Wires scheduler and N workers; owns lifecycle; the entry point | lifecycle state, worker list |

Supporting types: `RuntimeState` (enum: `NEW`, `RUNNING`, `STOPPING`,
`STOPPED`) and errors (`TaskCancelledError`, `RuntimeClosedError`,
`RuntimeNotStartedError`, and an internal `SchedulerClosedError`).

Task and Worker are deliberately unrelated types: a task never touches a
thread, a worker never inspects task state (`coding-standards.md` §5).

### Relations

```text
Runtime ──owns──▶ Scheduler «protocol» ◁── GlobalQueueScheduler
   │                    ▲
   │                    │ Worker depends only on the "next_task" view
   └──owns──▶ Worker × N┘

Runtime.spawn ──creates──▶ Task ◀──wraps── TaskHandle (returned to caller)
Scheduler stores Task references; Worker calls Task.run()
```

- Composition throughout; the only inheritance is a class implementing a
  protocol.
- `Worker` holds a thread rather than being one.
- `Runtime` receives its `Scheduler` by injection, defaulting to
  `GlobalQueueScheduler`.

### Narrow interfaces (interface segregation)

| Consumer | Sees only |
|---|---|
| `Worker` | `next_task()` — a "task source" |
| `Runtime` | `submit`, `close`, `drain` |
| `TaskHandle` | the public read/cancel surface of `Task` |

## 2. Task states

```text
PENDING ──worker claims──▶ RUNNING ──callable returns──▶ COMPLETED
   │                          └──────callable raises───▶ FAILED
   └──cancel / shutdown-cancel──▶ CANCELLED
```

| State | Meaning | Terminal | Entered by |
|---|---|---|---|
| `PENDING` | Created by `spawn` and queued; no worker has claimed it. Creation and enqueue are one step, so there is no separate "created" state. | no | `Runtime.spawn` |
| `RUNNING` | Claimed by exactly one worker, which is executing the callable | no | Worker, via claim |
| `COMPLETED` | Callable returned; result slot set | yes | Worker |
| `FAILED` | Callable raised; exception captured for the handle | yes | Worker |
| `CANCELLED` | Cancelled before any worker claimed it; callable never ran | yes | Caller (handle) or shutdown-cancel |

Legal transitions (everything else is illegal and must raise):

| From | To | Trigger |
|---|---|---|
| `PENDING` | `RUNNING` | Worker claims the task |
| `PENDING` | `CANCELLED` | `cancel()` or shutdown in cancel mode |
| `RUNNING` | `COMPLETED` | Callable returned |
| `RUNNING` | `FAILED` | Callable raised |

Invariants:

1. Terminal states are final; no transition leaves them.
2. A task reaches exactly one terminal state, exactly once.
3. `PENDING→RUNNING` and `PENDING→CANCELLED` are mutually exclusive: the
   check-and-change of state is atomic under the task's lock, so exactly
   one wins. The loser observes the other's result and does nothing.
4. The outcome (result or exception) is written **before** the state
   becomes terminal and before the completion event is set. Readers wait on
   the event and read the outcome afterwards.
5. Every submitted task eventually reaches a terminal state, provided the
   runtime is shut down (see §6).

There is no `WAITING`/`SUSPENDED` state; see `scope.md` §3 and ADR-001.

## 3. Component designs

### 3.1 Task

- **Immutable after construction:** identifier, callable, positional and
  keyword arguments.
- **Guarded by the task lock:** the state field. The lock is held only for
  the compare-and-change of state, never while user code runs.
- **Written once before the terminal transition:** result or exception.
- **Completion signal:** a blocking event that is set after the terminal
  state and outcome are in place.
- **Operations:**
  - `run` (worker thread only). Steps: try to claim (`PENDING→RUNNING`); if
    the claim fails because the task was cancelled, return without running
    anything. Otherwise call the callable outside the lock. On normal
    return, record the result and move to `COMPLETED`. On an ordinary
    exception, record it and move to `FAILED`. On a non-ordinary
    (`BaseException`) failure, record it, move to `FAILED` so waiters never
    hang, then re-raise so the worker crashes loudly.
  - `cancel` (any thread). Try `PENDING→CANCELLED`. Returns whether the task
    is now cancelled. Sets the completion event on success.
  - Read accessors: current state, done, wait-for-completion, result,
    exception.
- **Extension point:** the step that actually invokes the callable is a
  single overridable hook (template-method style), so a future task kind can
  change how it executes without changing state handling. Suspendable tasks
  would additionally change the Worker/Scheduler contract; that is a known
  consequence recorded in ADR-001, not built here.

### 3.2 TaskHandle

- Holds one task; exposes: state, done, result(timeout), exception(timeout),
  cancel.
- `result` returns the value for `COMPLETED`, re-raises the captured
  exception for `FAILED`, raises `TaskCancelledError` for `CANCELLED`, and
  raises a timeout error if the wait expires.
- The handle has no way to trigger any transition other than `cancel`.

### 3.3 Scheduler protocol

Operations and contract (every implementation must honor this and pass the
shared contract tests):

| Operation | Contract |
|---|---|
| `submit(task)` | Accepts a task for eventual execution. Raises `SchedulerClosedError` if closed. Acceptance is atomic with respect to `close`: a task is either accepted before close (and will be delivered or drained) or rejected. |
| `next_task()` | Called by workers. Blocks until a task is available, and returns it; returns "no task" only when the scheduler is closed **and** no work remains for this caller. Never returns the same task to two callers. |
| `close()` | Idempotent. After it, `submit` rejects. Wakes all blocked `next_task` callers. |
| `drain()` | Atomically removes and returns all tasks still queued. |

Ordering guarantees are implementation-specific and must be documented by
each implementation.

### 3.4 GlobalQueueScheduler

- State: a double-ended queue of tasks and a closed flag, both guarded by
  one lock with an associated wait/notify condition.
- Ordering: FIFO. Bound: unbounded.
- `submit`: under the lock, reject if closed; otherwise append and wake one
  waiter.
- `next_task`: under the lock, wait while the queue is empty and not closed
  (a blocking wait, not a spin); then return the oldest task, or "no task"
  if closed and empty.
- `close`: under the lock, set the flag and wake all waiters.
- `drain`: under the lock, take everything out and return it.
- Lock hold time: O(1) per operation (except `drain`, O(queued), used only
  at shutdown). No user code runs under this lock.
- Why not a lock-free stdlib queue: rejecting submits after close must be
  atomic with enqueueing, otherwise a task can be enqueued after workers
  have exited and remain `PENDING` forever (ADR-003).

### 3.5 Worker

- Owns its thread; the thread's only job is: fetch a task from the task
  source; if none, exit; otherwise call the task's `run`; repeat.
- Depends only on the task-source view of the scheduler.
- Lifecycle is explicit: start (creates and starts the thread), join
  (waits for exit). It stops only when the scheduler reports "no task".
- If the worker loop exits due to an exception (a re-raised
  `BaseException` from a task, or a scheduler bug), the exception is stored
  in a field written by the worker thread and read by the runtime only
  after join (single-owner handoff), and is also allowed to propagate so it
  is visible loudly through the normal thread-exception path.

### 3.6 Runtime

- **State:** `RuntimeState`, guarded by a short-held lifecycle lock; it is
  never held while joining workers or running user code.
- **Construction:** takes a **required** explicit `n_workers` (no default;
  ADR-003) and an optional scheduler. `n_workers` must be an integer of at
  least one; anything else is rejected at construction with a clear error.
  The count is fixed for the runtime's lifetime.
- **`start`:** `NEW→RUNNING`; creates and starts N workers. Calling it in
  any other state is an error.
- **`spawn(fn, *args, **kwargs)`:** requires the runtime to have been
  started; creates a task; submits it; returns a handle. A
  `SchedulerClosedError` from the scheduler is translated to
  `RuntimeClosedError`. Correctness of "no task accepted after shutdown
  begins" rests on the scheduler's atomic close, not on reading the
  runtime state.
- **`shutdown(cancel_pending=False)`:**
  1. Under the lifecycle lock: if the state is not `RUNNING`, return (so
     shutdown is idempotent); otherwise set `STOPPING`.
  2. Close the scheduler.
  3. If `cancel_pending`: drain the scheduler and cancel each drained task.
     Otherwise leave pending tasks; workers will finish them (drain mode).
  4. Join all workers.
  5. Final safety sweep: drain again and cancel anything left (covers the
     case where every worker crashed and tasks were stranded).
  6. Set `STOPPED`; if any worker recorded a crash, raise it.
- **Context manager:** entering starts the runtime; leaving calls shutdown
  in drain mode.

### 3.7 Keeping cancellation policy changeable

Phase 1 cancels pending tasks only, but the design must let a later phase
change that (for example, cooperative cancellation of running tasks)
without redesigning the entities. The following seams are required in the
implementation; the future mechanism itself is **not** built now.

1. **One transition table.** The legal transitions in §2 live in a single
   data structure in the task module, and every state change goes through
   one method that consults it. Allowing a new transition (for instance
   `RUNNING→CANCELLED`) or adding a state is then a table change plus
   tests, not a hunt through the code.
2. **One cancellation entry point per layer.** `Task.cancel` is the only
   place that decides whether cancellation succeeds; `TaskHandle.cancel`
   and shutdown-cancel both delegate to it. Nothing else may encode the
   "pending only" rule.
3. **Contract phrased as a request.** `cancel` is documented as "request
   cancellation; returns whether the task is now cancelled", not as "cancel
   a pending task". Callers and tests must rely on the returned value and
   the observable state, never on the assumption that a running task can't
   be cancelled.
4. **Intent separable from state.** A future design would need a way for a
   running callable to learn a cancel was requested (a flag or token) and a
   choice between going straight `RUNNING→CANCELLED` or via an intermediate
   `CANCELLING` state. That choice is deferred to a future ADR; Phase 1
   stores no cancellation-request data.
5. **Hook for opt-in tokens.** The overridable invocation hook (§3.1) is
   where a future task kind could pass a cancellation token to the callable.
   `Worker` and `Scheduler` need no change for cooperative cancellation
   because the worker treats `run` as opaque.
6. **Shutdown policy stays local.** Shutdown-cancel goes through
   `Task.cancel`, so a future "cancel running tasks at shutdown" policy is a
   change to the runtime's shutdown policy only.

Each seam is checked in `verification.md` §2 and §5.

## 4. Ownership and synchronization summary

Every piece of shared mutable state, who may touch it, and what protects it
(required by `coding-standards.md` §3–§4).

| State | Owner | Who may mutate | Protection | Invariant protected |
|---|---|---|---|---|
| Task state | `Task` | Worker (claim, finish); any thread via `cancel` | per-task lock | Legal transitions only; claim and cancel are mutually exclusive |
| Task result / exception | `Task` | The one worker that claimed the task | write-once, ordered before the completion event | Outcome visible to waiters before they read it |
| Task completion event | `Task` | Worker or canceller (set once) | the event itself (blocking primitive) | Waiters wake exactly when terminal |
| Scheduler queue and closed flag | `GlobalQueueScheduler` | Any submitter, any worker, runtime (close, drain) | scheduler lock + condition | No task accepted after close; no task delivered twice |
| Worker crash record | `Worker` | The worker thread only | single-owner; read by runtime only after join | Crash surfaced exactly once |
| Runtime state | `Runtime` | Caller of start / shutdown | lifecycle lock (short-held) | State moves forward only; shutdown idempotent |
| Worker list | `Runtime` | Set in `start`, read in `shutdown` | lifecycle ordering (start happens-before shutdown) | Every started worker is joined |

Deviation note against "prefer queues over locks" (`coding-standards.md`
§4): two locks are used. Both are justified in ADR-003, are held O(1) with
no user code beneath them, and each gets a comment naming what it protects.
No spin loops exist; every wait is a blocking primitive.

## 5. Error handling summary

| Situation | Behavior |
|---|---|
| Task callable raises `Exception` | Task → `FAILED`; exception delivered via handle; worker continues |
| Task callable raises `BaseException` | Task → `FAILED` (waiters released); exception re-raised; worker crashes loudly and records it; runtime surfaces it at shutdown |
| Scheduler / worker infrastructure bug | Fails loudly; never swallowed; no silent degradation |
| `spawn` before `start` | `RuntimeNotStartedError` |
| `spawn` after shutdown began | `RuntimeClosedError` |
| `result()` on a cancelled task | `TaskCancelledError` |
| `cancel()` on a running or finished task | Phase 1 policy: returns "not cancelled"; no state change (policy lives only in `Task.cancel` and the transition table, §3.7) |
| `n_workers` missing, non-integer or below one | Rejected at `Runtime` construction with a clear error |
| Illegal state transition attempt | Raises; treated as a bug |

No bare `except`; only specific exception classes are caught, with the
`BaseException` path re-raising.

## 6. Liveness argument

- **Drain mode:** workers keep fetching until the closed queue is empty, so
  all pending tasks run and finish.
- **Cancel mode:** pending tasks are drained and cancelled; tasks already
  claimed run to completion.
- **Crash path:** a task that crashes its worker is marked `FAILED`, so its
  waiters are released. Tasks left in the queue if all workers die are
  cancelled by the final sweep.
- **Not covered:** deadlock among blocked tasks (`scope.md` §3, limitations
  1–2).

## 7. Module layout (proposed)

| Module | Contents |
|---|---|
| `errors` | Error types |
| `task` | `TaskState`, `Task` |
| `handle` | `TaskHandle` |
| `scheduler` | `Scheduler` protocol, task-source view, `GlobalQueueScheduler` |
| `worker` | `Worker` |
| `runtime` | `RuntimeState`, `Runtime` |
| `tests/` | Unit, contract, integration and stress tests (see `verification.md` §5) |

Exact package name and layout are finalized in increment S0 and recorded in
the tracker.

## 8. Documentation obligations for code (from the coding standards)

- Type hints on every public function, class and method.
- A module- or class-level docstring stating owned state, permitted
  threads, and explicit non-guarantees.
- A one-line comment beside each piece of shared mutable state naming its
  protection and invariant.
- No performance claims in comments.
