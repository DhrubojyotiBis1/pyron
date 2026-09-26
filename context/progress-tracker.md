# Progress Tracker

> This file represents the **actual, current state** of the project. If
> something is not listed under "Completed" with evidence (code + tests),
> it is not done — regardless of what `architecture-context.md` describes.
> Last updated: 2026-09-26 (S6 complete; post-Phase-1 CPU-saturation benchmark script added)

## Current phase

**Phase 1 — Minimal M:N scheduler (1 global queue, N workers). Status: COMPLETE (S0–S6 done; exit criteria met — see Validation status).**

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
are `DECIDED`; ADR-003 was `PROPOSED` except its worker-count clause
(`DECIDED`). At S6 all three ADRs were promoted to `CONFIRMED` with
evidence recorded in each ADR entry (`architecture-context.md` §8).

## Implementation progress: S6/7 (100% of the Phase 1 plan)

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
- **S6 COMPLETE**: Stress and race hardening; documentation promotion ✓
  - `tests/test_s6_stress.py` (9 stress tests): claim vs cancel with 4 cancellers, close vs submit, fetch vs shutdown-cancel, handle-cancel racing shutdown-cancel, tasks spawning children mid-shutdown (both modes), 6 concurrent `shutdown()` callers, 20-round soak (60 000 tasks, no thread leaks), and the documented starvation limitation ✓
  - ADR-001..003 promoted to `CONFIRMED`; `phase-1/verification.md` §6 checklist completed; status headers swept across `context/` ✓
  - All 160 tests (S0–S6) passing ✓
- No work-stealing implementation exists.
- No general benchmark suite exists. One standalone script does: `benchmarks/cpu_saturation.py`
  (CPU-utilisation / scaling sweep; not run by pytest). Its one recorded run is Experiment 1 below.
  It is a measurement tool outside the runtime, not a Phase 1 deliverable; no `pyron/` code changed.

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

*(nothing — Phase 1 complete; next phase not yet scoped)*

## Planned (not started)

Phase 1 increments, in order (details in `phase-1/plan.md` §3):

1. ~~S0~~ ✓ DONE
2. ~~S1~~ ✓ DONE
3. ~~S2~~ ✓ DONE
4. ~~S3~~ ✓ DONE
5. ~~S4~~ ✓ DONE
6. ~~S5~~ ✓ DONE
7. ~~S6~~ ✓ DONE

Deferred until after Phase 1 (not queued, not scheduled): a general
benchmarking harness beyond `benchmarks/cpu_saturation.py` (required before
any further performance claim — see `coding-standards.md` §10),
work-stealing scheduler, suspension/waiting state, backpressure.

Note: this list is intentionally short. Long speculative roadmaps belong
in `project-overview.md` §4 (vision) at most, not here — this section
should only ever list what's actually queued to start next.

## Blocked / unresolved

- Nothing blocks Phase 1. Open architectural questions (queue topology,
  task granularity, backpressure, blocking tasks) remain open in
  `architecture-context.md` §5 and need a general benchmark harness, which is
  deferred past Phase 1 (only `benchmarks/cpu_saturation.py` exists).

## Experiments performed

### Experiment 1 — CPU saturation: Pyron vs raw threads vs processes — 2026-09-26
Question: How much of the machine's CPU can a `Runtime` keep busy on a
CPU-bound pure-Python workload, and how much of what the machine/interpreter
allows does it deliver, as worker count and task size vary?

Method: `benchmarks/cpu_saturation.py` (run as
`.venv/bin/python benchmarks/cpu_saturation.py --json …`; the `procs` control
row needs `--with-processes`). Fixed CPU work (~3 s serial) is cut into tasks
of 10 / 1 / 0.1 ms and run serially, on T raw `threading.Thread`s pulling from
a lock-guarded counter (`raw`, the cheapest dynamic dispatch), and on
`Runtime(n_workers=T)` with one producer (`pyron`); T = 1, 2, 4, 8, 16. Metrics:
process CPU time (user+sys, all threads) / wall / logical CPUs ("util"), and
speedup vs serial. Median of 3 repetitions; every task result is verified and
distinct worker threads are counted. Control (1 ms tasks, T = 4 and 8, 3 reps):
the same work over separate processes (`procs`).
Environment: Apple M2 (4 performance + 4 efficiency cores, 8 logical CPUs),
macOS 26.2 arm64, AC power, CPython 3.14.7 free-threaded (GIL disabled), Pyron
0.0.1-phase1 at base commit 35c3437 with the script as an uncommitted
working-tree file at run time. One machine, one session, runs of seconds.

Result (8 workers unless noted; all `pyron` unless noted):

| Task size | cores busy | util | speedup | `raw` speedup | pyron ÷ raw throughput |
|---|---|---|---|---|---|
| 10 ms | 6.80 | 85% | 3.58× | 3.69× | 97% |
| 1 ms | 7.43 | 93% | 3.55× | 3.61× | 98% |
| 0.1 ms | 7.54 | 94% | 3.87× | 4.17× | 93% |

- Peak CPU utilisation seen: 95.2% (7.62 of 8 logical CPUs) at 16 workers,
  1 ms tasks. 1 / 2 / 4 workers used ≈1.0 / 2.0 / 4.0 cores (up to 1.13 / 2.19 / 4.32 at
  0.1 ms, where the producer thread's CPU shows), i.e. util scales with T.
- Pyron's throughput vs `raw` at the same T ranged 89–101% over all rows;
  at 0.1 ms it was 89–93% and its kernel-time share was 1.7–5.6% vs 0.5–1.2%
  for `raw`. At 1 worker / 0.1 ms the gap (9 083 vs 9 933 tasks/s) is
  ≈ 9 µs of extra cost per task (derived from those two rows).
- Speedup reached only 3.4–4.2× at 8+ threads even though ~7.5 cores were busy,
  and `raw` threads showed the same. Control (1 ms): 8 processes reached 4.53×
  (7.32 cores busy) vs 3.67× for 8 raw threads and 3.56× for 8 Pyron workers.
- Run-to-run spread of wall time ((max−min)/median over 3 runs) at 8+ threads
  ranged 1.6–19%; large enough that differences of a few percent are noise.
- A GIL-enabled interpreter run (`--allow-gil`, smoke length) gave 1.01 cores
  busy and 0.99× speedup at 8 threads, i.e. the script does distinguish real
  parallelism from none.

Conclusion: On this machine `Runtime` can drive the process to roughly 85–95%
of all logical CPUs' time, and tracks a minimal raw-thread dispatcher within
~4% for tasks ≥ 1 ms and ~7–11% at 0.1 ms. The dominant limit on *useful*
speedup is not Pyron: a mixed 4P+4E machine caps below 8×, and threads in one
free-threaded interpreter reach roughly 80% of what separate processes do here
(3.67× vs 4.53×) with or without Pyron. Why threads trail processes was not
investigated. The 0.1 ms overhead and its higher kernel-time share are
*consistent with* single-lock queue/condition-variable cost, but that is a
hypothesis: no experiment isolated it. The 85% at 10 ms is unexplained (only
300 tasks per run; tail imbalance is one candidate, untested). Not
established: behaviour on other hardware/OSes/Python builds, runs longer than
seconds or under thermal throttling, multiple producers beyond a smoke test
(`--producers`), or any comparison with `ThreadPoolExecutor`.

Follow-up: none queued. If pursued: repeat on a homogeneous-core machine;
vary producers at 0.1 ms and below; a longer sustained run
(`--work-seconds 60`); profile where the ~9 µs/task goes.

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

- 2026-09-26 (S6) — **Concurrency-safety evidence.** Races probed and how:
  - claim vs cancel: 2 000 tasks × 10 rounds, 4 workers, 4 threads cancelling in shuffled order; each task ended exactly one of ran/`COMPLETED` or `CANCELLED`, never both, never neither.
  - close vs submit (scheduler): 300 rounds, 4 submitters racing `close` behind a barrier; every accepted task was delivered exactly once, none stranded, nothing accepted after close.
  - fetch vs shutdown-cancel: 1 000 tasks × 50 rounds, plus handle-cancel racing shutdown-cancel (30 rounds); "callable ran" held iff `COMPLETED`.
  - spawn during shutdown: external spammers (S5) and tasks spawning children (S6), both modes; every accepted handle reached a terminal state; late spawns got `RuntimeClosedError`.
  - concurrent `shutdown()` callers: 50 rounds × 6 threads mixing modes; no exception, workers joined, final state `STOPPED`.
  - soak: 20 rounds × 3 000 tasks × 8 workers with 4 submitter threads; no thread leaks.
  Repeat-run record: the S6 file passed 60 consecutive runs and the full suite 60 consecutive runs (then 50 more after adding the last test), all on free-threaded 3.14.7 with the GIL disabled. Not evidence of absence of races — a bounded sample on one machine.
- 2026-09-26 (S6) — **Two test-only flakes found and fixed by repeated runs; neither was a runtime bug.** (1) `test_worker_start_creates_thread` and the `join` test in `test_s4_worker.py` closed the scheduler before asserting the worker thread was alive, so the worker could exit first; they now keep the scheduler open until after the assertion. (2) The new starvation test let the first parent spawn its child before the second parent had been claimed, so an idle worker ran the child; parents now meet at a barrier so every worker is occupied first. Lesson recorded: single passing runs are not enough for these tests; the repeated-run loop caught both.
- 2026-09-26 (S6) — **Deadlock limitation demonstrated.** With 2 workers and 2 parent tasks each waiting on a queued child, no child ran until a parent's 1 s wait timed out (`scope.md` §3.2). Recorded, not fixed.

*(further findings — populated as experiments produce results, including negative
or inconclusive ones)*

## Validation status

Full suite: 160 tests passing, no warnings (2026-09-26, free-threaded CPython
3.14.7, GIL disabled — asserted by `tests/conftest.py`).
Per component (S0–S6): tested as listed under Implementation progress.
Known-untested: runs longer than seconds (no hours-long soak); other
platforms and Python versions (only macOS / Darwin, 3.14.7t); resource
exhaustion beyond the simulated thread-start failure; a second `Scheduler`
implementation (only the global queue exists).
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
| 2026-09-26 | **S6 Complete**: stress and race hardening; documentation promotion. Added `tests/test_s6_stress.py` (9 tests) and an exact-N-workers test; fixed two racy test assertions in `tests/test_s4_worker.py`; promoted ADR-001..003 to `CONFIRMED` with evidence; completed `phase-1/verification.md` §6; swept stale status headers in `context/` (project-overview, plan, scope, implementation, architecture-context). 160 tests passing. Phase 1 complete. | Claude Sonnet 5 |
| 2026-09-26 | Added `benchmarks/cpu_saturation.py` (standalone CPU-utilisation/scaling benchmark; no `pyron/` changes) and recorded Experiment 1. Updated stale "no benchmark" statements here, in `README.md` and in `architecture-context.md` §5. Script not yet committed at time of writing. | Claude Sonnet 5 |
