# Progress Tracker

> This file represents the **actual, current state** of the project. If
> something is not listed under "Completed" with evidence (code + tests),
> it is not done — regardless of what `architecture-context.md` describes.
> Last updated: 2026-09-26 (S5 complete)

## Current phase

**Phase 1 — Minimal M:N scheduler (1 global queue, N workers). Status: IN PROGRESS (S0–S5 complete, S6 next).**

Phase 0 (initialization: persistent context system) is complete.

### Current plan

The Phase 1 plan lives in [`phase-1/`](phase-1/plan.md):

| Document | Contents |
|---|---|
| [`phase-1/plan.md`](phase-1/plan.md) | Goal, approach, increments S0–S6, exit criteria, risks, recorded sign-off decisions |
| [`phase-1/scope.md`](phase-1/scope.md) | In scope, out of scope, known limitations of the phase |
| [`phase-1/implementation.md`](phase-1/implementation.md) | Entities, task states, low-level design, ownership and synchronization |
| [`phase-1/verification.md`](phase-1/verification.md) | Design-time verification (done on paper) and code-time test plan (pending) |

The five sign-off decisions were answered on 2026-09-26 (`phase-1/plan.md`
§6): five task states, pending-only cancellation (with a design that keeps
it changeable), `Scheduler` as the swappable seam, crash-loudly on
`BaseException`, and a required explicit `n_workers`. ADR-001 and ADR-002
are `DECIDED`; ADR-003 is `PROPOSED` except its worker-count clause
(`DECIDED`). Nothing is `CONFIRMED` yet: components S0–S4 exist with tests, but no ADR has been promoted (planned for S6).

## Implementation progress: S5/7 (≈86%)

- **S0 COMPLETE**: Environment and scaffolding ✓
  - Free-threaded Python build (3.14.7) verified; GIL disabled ✓
  - Package layout created: `pyron/`, `tests/` ✓
  - pytest installed and configured ✓
  - 5 environment verification tests passing ✓
- **S1 COMPLETE**: Errors, TaskState, Task ✓
  - Error types: TaskCancelledError, RuntimeClosedError, RuntimeNotStartedError, SchedulerClosedError ✓
  - TaskState enum with 5 states and is_terminal() method ✓
  - Task: guarded state machine with lock, outcome slots, completion event ✓
  - 32 unit tests: transitions, races, timeouts, exceptions, cancellation ✓
- **S2 COMPLETE**: TaskHandle ✓
  - TaskHandle: public caller-facing wrapper around Task ✓
  - Methods: state(), done(), result(timeout), exception(timeout), cancel() ✓
  - 38 unit tests: state views, timeouts, exception propagation, cancellation, concurrency ✓
  - Thread-safe for concurrent result/exception/cancel calls ✓
- **S3 COMPLETE**: Scheduler protocol + GlobalQueueScheduler ✓
  - Scheduler protocol: submit, next_task, close, drain (swappable seam for future schedulers) ✓
  - GlobalQueueScheduler: FIFO queue under single lock + condition variable ✓
  - 21 contract tests: FIFO ordering, close/submit atomicity, drain atomicity, blocking behavior ✓
  - Multiple workers verified: no task lost, each task retrieved by exactly one worker ✓
  - All 96 tests (S0+S1+S2+S3) passing ✓
- **S4 COMPLETE**: Worker ✓
  - Worker: owns one non-daemon thread; loop = `next_task()` → `task.run()`; exits on "no task" ✓
  - `BaseException` from a task is recorded (`crash()`, read after `join`) and re-raised (loud crash) ✓
  - Ordinary `Exception` marks the task FAILED and the worker continues ✓
  - 20 tests: lifecycle, join timeout, crash recording (custom BaseException, KeyboardInterrupt, SystemExit), multi-worker (3 workers, 20 tasks), drain vs running worker ✓
  - All 116 tests (S0-S4) passing ✓
- **S5 COMPLETE**: Runtime ✓
  - `Runtime(n_workers, scheduler=None)`: required explicit `n_workers` (TypeError for non-int/bool, ValueError < 1) ✓
  - Lifecycle NEW → RUNNING → STOPPING → STOPPED under a short-held lifecycle lock never held while joining ✓
  - `spawn` → `TaskHandle`; `RuntimeNotStartedError` / `RuntimeClosedError` (scheduler's atomic close is the source of truth) ✓
  - `shutdown(cancel_pending=False)`: close → optional drain+cancel → join → final sweep → STOPPED → raise first worker crash (once); idempotent ✓
  - Context manager (drain-mode shutdown on exit) ✓
  - Public API exported from `pyron/__init__.py` ✓
  - 32 tests: 1000 tasks on 4 workers each run exactly once on ≤4 threads; both shutdown modes; crash surfaced once; all-workers-dead final sweep; start-failure cleanup; spawn-vs-shutdown stress (both modes) ✓
  - All 148 tests (S0–S5) passing; S5 file run 25× with no failures ✓
- No work-stealing implementation exists.
- No benchmark suite exists.

## Completed

| Item | Evidence |
|---|---|
| Project context system created (`context/`, `AGENTS.md`, `CLAUDE.md`) | This file set |
| Phase 1 plan documents written (plan, scope, implementation, verification) | `phase-1/*.md` — documentation only; design-time checks in `phase-1/verification.md` §1–§4, no code-level validation |
| **S0 — Environment and scaffolding** | `pyron/`, `tests/conftest.py`, `pytest.ini`, `tests/test_s0_environment.py` with 5 passing tests; free-threaded build confirmed, GIL disabled |
| **S1 — Errors, TaskState, Task** | `pyron/errors.py`, `pyron/task.py`, `tests/test_s1_task.py` with 32 passing tests; state machine verified, cancel-vs-claim race tested, timeout behavior validated |
| **S2 — TaskHandle** | `pyron/handle.py`, `tests/test_s2_handle.py` with 38 passing tests; public API verified, timeout behavior, exception propagation, concurrent access tested |
| **S3 — Scheduler protocol + GlobalQueueScheduler** | `pyron/scheduler.py`, `tests/test_s3_scheduler.py` with 21 passing tests; FIFO ordering verified, close/submit atomicity, drain atomicity, multi-worker access tested |
| **S4 — Worker** | `pyron/worker.py`, `tests/test_s4_worker.py` with 20 passing tests; clean exit on close, crash recording, exception vs BaseException handling, multi-worker on one scheduler |
| **S5 — Runtime** | `pyron/runtime.py`, `tests/test_s5_runtime.py` with 32 passing tests; lifecycle, both shutdown modes, crash surfacing, final sweep, spawn-vs-shutdown stress |

## In progress

- **S6 — stress/race hardening, ADR promotion** (queued to start next)

## Planned (not started)

Phase 1 increments, in order (details in `phase-1/plan.md` §3):

1. ~~S0~~ ✓ DONE
2. ~~S1~~ ✓ DONE
3. ~~S2~~ ✓ DONE
4. ~~S3~~ ✓ DONE
5. ~~S4~~ ✓ DONE
6. ~~S5~~ ✓ DONE
7. **S6 — stress/race hardening; promote ADRs; update this tracker.** (next)

Deferred until after Phase 1 (not queued, not scheduled): benchmarking
harness (required before any performance claim — see
`coding-standards.md` §10), work-stealing scheduler, suspension/waiting
state, backpressure.

Note: this list is intentionally short. Long speculative roadmaps belong
in `project-overview.md` §4 (vision) at most, not here — this section
should only ever list what's actually queued to start next.

## Blocked / unresolved

- ADR-003's synchronization and shutdown details (lock structure, two
  shutdown modes, final sweep) are still `PROPOSED`; they must be reviewed
  before S5 starts, since `Runtime` implements them.

## Experiments performed

*(none yet)*

When an experiment is run, record it here using this format, regardless of
outcome:

```text
### Experiment N — <short title> — <date>
Question:
Method:
Result:
Conclusion: (including "inconclusive" if that's honest)
Follow-up:
```

## Findings

- 2026-09-26 (S4): a test that leaves a `Worker` blocked in `next_task()` (scheduler never closed) hangs the whole pytest process at exit, because worker threads are non-daemon. This is expected Worker behavior, not a bug: workers stop only on scheduler close (`phase-1/implementation.md` §3.5). Consequence for tests and later for `Runtime`: every started worker must be released by `close()` and joined, including on failure paths. Mitigation added: tests clean up in `finally`; `pytest-timeout` (30 s, thread method) is a dev dependency so a hang fails instead of blocking.

*(further findings — populated as experiments produce results, including negative
or inconclusive ones)*

## Validation status

Full suite: 148 tests passing, no warnings (2026-09-26, free-threaded 3.14.7).
Per component (S0–S5): tested as listed under Implementation progress.
Known-untested: long/sustained stress and repeated-run hardening (S6); a
task calling `spawn` on its own runtime during shutdown; behavior under
resource exhaustion beyond the simulated thread-start failure.
Known limitations: concurrent `shutdown()` callers other than the one that
performs the shutdown return immediately without waiting; `shutdown()` from
a worker thread raises `RuntimeError`; if several workers crashed only the
first recorded crash is raised. Tests that
intentionally crash a worker with `BaseException` carry a `filterwarnings`
mark for the expected unhandled-thread-exception warning.

Known design-level risks already recorded (not yet code): deadlock when all
workers run tasks blocked on queued tasks; single-lock global queue
contention (a hypothesis, unmeasured). See `phase-1/scope.md` §3.

## Open questions

See `architecture-context.md` §5 for the current list of unresolved
architectural questions. This section should only duplicate an entry from
there if it has become blocking for planned work — otherwise, keep
questions in one place.

## Changelog

| Date | Change | By |
|---|---|---|
| 2026-08-31 | Initialized project context system; established Phase 0 | initial setup |
| 2026-09-26 | Wrote Phase 1 plan (`context/phase-1/`); moved current phase to Phase 1 (planned); added ADR-001..003 as `PROPOSED`; annotated open questions in `architecture-context.md`. Documentation only, no code. | Claude Code |
| 2026-09-26 | Recorded owner sign-off on the five Phase 1 decisions: ADR-001 and ADR-002 → `DECIDED`; ADR-003 worker-count clause → `DECIDED` (required explicit `n_workers`), rest still `PROPOSED`. Added cancellation-changeability seams (`phase-1/implementation.md` §3.7) and matching verification items. Documentation only, no code. | Claude Code |
| 2026-09-26 | **S0 Complete**: Environment and scaffolding. Created `pyron/` package, `pytest.ini`, `.venv` with pytest, `tests/conftest.py` with GIL assertion, and `tests/test_s0_environment.py` with 5 passing tests. Free-threaded Python 3.14.7 verified with GIL disabled. Ready to begin S1. | Claude Haiku 4.5 |
| 2026-09-26 | **S1 Complete**: Errors, TaskState, Task. Implemented `pyron/errors.py` (4 error types), `pyron/task.py` (state machine with 5 states, outcome slots, completion event, guarded by per-task lock). Created `tests/test_s1_task.py` with 32 unit tests covering transitions, cancel-vs-claim race (100 iterations), timeouts, exceptions (Exception vs BaseException). All 37 tests passing (S0 + S1). Git repo initialized with remote; initial commit pushed. | Claude Haiku 4.5 |
| 2026-09-26 | **S2 Complete**: TaskHandle. Implemented `pyron/handle.py` (public wrapper: state(), done(), result(timeout), exception(timeout), cancel()). Created `tests/test_s2_handle.py` with 38 tests covering state views, timeouts, exception propagation, cancellation, concurrent access (5 threads waiting on same handle). All 75 tests passing (S0 + S1 + S2). TaskHandle verified thread-safe for concurrent operations. | Claude Haiku 4.5 |
| 2026-09-26 | **S3 Complete**: Scheduler protocol + GlobalQueueScheduler. Implemented `pyron/scheduler.py` with Scheduler protocol (submit, next_task, close, drain) and GlobalQueueScheduler (FIFO queue, single lock+condition, O(1) ops). Created `tests/test_s3_scheduler.py` with 21 tests: FIFO ordering, close/submit atomicity, drain atomicity, blocking behavior, multi-worker access (4 workers, 20 tasks, no loss, no duplication). All 96 tests passing (S0+S1+S2+S3). Scheduler seam verified as swappable for future work-stealing. | Claude Haiku 4.5 |
| 2026-09-26 | **S4 Complete**: Worker. Implemented `pyron/worker.py` (one non-daemon thread; fetch/run loop; records and re-raises `BaseException`; `crash()` read after `join`). `tests/test_s4_worker.py` with 20 tests. Diagnosed a pytest hang as a leaked blocked worker in two tests (scheduler never closed); fixed with `finally` cleanup and added `pytest-timeout` (30 s, thread method) to dev deps and `pytest.ini`. 116 tests passing (S0-S4). | Claude Sonnet 5 |
| 2026-09-26 | Pre-S5 cleanup: re-ran full suite (116 passing); silenced the expected thread-exception warning on the four intentional-crash tests; corrected stale tracker text (header, phase status, "no code exists", validation status, blocked list). | Claude Sonnet 5 |
| 2026-09-26 | **S5 Complete**: Runtime. Implemented `pyron/runtime.py` exactly per ADR-003 as written (lifecycle lock, drain/cancel shutdown, final sweep, crash surfaced once) plus start-failure cleanup and a guard against `shutdown()` from a worker thread. Exported public API from `pyron/__init__.py`. `tests/test_s5_runtime.py` with 32 tests; 148 passing (S0–S5), S5 file stable over 25 repeated runs. ADR-003 remains `PROPOSED` until S6. | Claude Sonnet 5 |
