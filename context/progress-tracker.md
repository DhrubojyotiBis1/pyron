# Progress Tracker

> This file represents the **actual, current state** of the project. If
> something is not listed under "Completed" with evidence (code + tests),
> it is not done — regardless of what `architecture-context.md` describes.
> Last updated: 2026-10-04 (Phase 2 in progress: P2.1 COMPLETE, accepted by the owner on the evidence of Experiments 2 and 4; primary benchmark environment for P2.2–P2.4 is the Claude Code cloud container; P2.2 next, after sign-off decision 4)

## Current phase

**Phase 2 — Measure, then decide. Status: IN PROGRESS — P2.1 COMPLETE (accepted by the owner on 2026-10-04: reproduction 37/40 within spread, Experiment 2; old/new A/B 39/40 within the noise floor, Experiment 4). Primary benchmark environment for P2.2–P2.4: the Claude Code cloud container (owner decision 2026-10-04; the M2 is secondary). Next: P2.2, after sign-off decision 4.**

Phase 1 (minimal M:N scheduler: 1 global queue, N workers) is COMPLETE
(S0–S6 done; exit criteria met — see Validation status). Phase 0
(initialization: persistent context system) is complete.

### Current plan

The Phase 2 plan lives in [`phase-2/`](phase-2/plan.md):

| Document | Contents |
|---|---|
| [`phase-2/plan.md`](phase-2/plan.md) | Goal, approach, increments P2.1–P2.6, exit criteria, risks, sign-off decisions, decision rules for Phase 3 |
| [`phase-2/scope.md`](phase-2/scope.md) | In scope, out of scope, known limitations of the phase's evidence |
| [`phase-2/implementation.md`](phase-2/implementation.md) | Benchmark harness design, design of each experiment, structure of ADR-004 |
| [`phase-2/verification.md`](phase-2/verification.md) | Design-time verification (done on paper) and execution-time checks (pending) |

Phase 2 adds no runtime features and changes nothing in `pyron/`. It builds
a shared benchmark harness, measures scheduler contention, end-to-end cost
against `ThreadPoolExecutor` and raw threads, and the per-task cost
breakdown, writes ADR-004 on handling blocking tasks, and then chooses the
Phase 3 track by decision rules fixed in advance. Sign-off decisions
answered on 2026-10-04 (`phase-2/plan.md` §6): a phase with no runtime
features is acceptable; raw benchmark JSON is not committed; the owner will
run homogeneous-core / other-OS repeats separately — amended the same day:
the Claude Code cloud container is the primary environment for P2.2–P2.4
and the M2 is secondary (`phase-2/plan.md` §6 decision 3). Pending: decision 4,
the Phase 3 decision rules (`phase-2/plan.md` §7), which must be signed off
before any P2.2–P2.4 result is looked at.

### Phase 1 plan (complete)

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

## Implementation progress: Phase 2 (P2.1 complete)

- **P2.1 COMPLETE (accepted by the owner, 2026-10-04)**: shared benchmark harness; `cpu_saturation.py` ported
  - `benchmarks/_harness.py`: `burn`, `calibrate_ns_per_iter`, `cpu_times`, `Window`, `gil_enabled`, `_cmd`
    moved unchanged from `cpu_saturation.py` (AST-identical); `Sample` / `Stats` / `summarize` generalized
    (configuration as a mapping; median, spread, min, max, cores, sys share — same arithmetic) ✓
  - New in the harness: `environment()` extended (usable CPUs, Linux core types by `cpu_capacity` or max
    frequency, Linux governor and AC/battery, loaded third-party extension modules); `require_free_threading()`
    checked at start-up and after every run; `beyond_spread()` / `rel_diff()`; `common_args()`
    (`--quick`, `--reps`, `--warmup`, `--json [PATH]`, `--allow-gil`); `json_path()` / `write_json()` with
    default folder `benchmarks/results/` (git-ignored); `watchdog()` (a hung run dumps all stacks and exits
    non-zero) ✓
  - `benchmarks/cpu_saturation.py` ported: the measured run bodies (`run_serial`, `run_raw_threads`,
    `run_processes`, `run_pyron`, `_proc_worker`) are unchanged apart from the error helper's name and how
    the returned `Sample` is built (both outside the timed window) ✓
  - Script-level default changes (recorded, not part of the move): 5 recorded repetitions (was 3) and
    1 unrecorded warm-up repetition (was none); `--reps 3 --warmup 0` restores Experiment 1's method.
    `--json` with no path writes to `benchmarks/results/` ✓
  - `run_threads()` deferred to P2.2 (first script that needs it; using it here would change measured code) —
    recorded in `phase-2/implementation.md` §1
  - `tests/test_bench_harness.py`: 36 tests (statistics, beyond-spread, GIL guard, environment parsing with fake
    sysfs, extension detection, CLI flags, JSON path, results folder ignored, watchdog fires in a subprocess and
    stays disarmed after its block) ✓
  - Smoke-checked by hand: `--quick` (with `--json`); `--with-processes`; `--producers 3`; warm-up samples excluded
    from JSON; `PYTHON_GIL=1` refused with exit 2 and accepted with `--allow-gil` (≈1 core, warning printed) ✓
  - Reproduction run of Experiment 1 done (Experiment 2): **37 of 40 rows within spread; pass condition not fully met.**
    The three rows outside run code the port did not change (two `raw`, one `serial`); two attempts to isolate port
    vs environment by an old/new A/B were spoiled by thermal throttling (Experiment 3)
  - Old/new A/B on a cloud VM (Experiment 4): 39 of 40 rows within the noise floor normalized; `serial` and `raw`
    paths unchanged (≤ ~0.4% pooled); an unexplained ≈ +2–3% on the Pyron path at 0.1 ms (open finding) ✓
  - **Owner decision 2026-10-04: P2.1 accepted on this evidence** — the pass condition in `phase-2/implementation.md`
    §3.1 was not literally met (37/40), the misses are in unchanged code, and Experiment 4 shows the port does not
    change the `serial`/`raw` paths. The ≈ 2–3% Pyron-path bias at 0.1 ms is carried forward as a known bias against
    Pyron (Findings), not resolved. No harness change was made as part of the acceptance ✓
- No `pyron/` code changed in Phase 2.

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
| **S6 — Stress and race hardening** | `tests/test_s6_stress.py` with 9 passing stress tests; ADR-001..003 `CONFIRMED`; `phase-1/verification.md` §6 complete |
| **P2.1 — Shared benchmark harness; `cpu_saturation.py` ported** | `benchmarks/_harness.py`, `benchmarks/cpu_saturation.py`, `tests/test_bench_harness.py` with 36 passing tests (196 in the full suite); Experiments 2 and 4; accepted by the owner on 2026-10-04 with the reproduction at 37/40 rows (see the P2.1 entry above) |

## In progress

- Nothing under way. P2.1 is complete; P2.2 has not started and waits on sign-off decision 4 (Blocked / unresolved).

## Planned (not started)

Phase 2 increments (details in `phase-2/plan.md` §3). P2.5 may run
alongside P2.2–P2.4; P2.6 comes last.

1. ~~P2.1~~ ✓ DONE (accepted 2026-10-04)
2. P2.2 — Scheduler contention baseline (incl. sharded-queue upper bound, hand-off latency)
3. P2.3 — End-to-end baseline: `Runtime` vs `ThreadPoolExecutor` vs raw threads across task sizes
4. P2.4 — Per-task cost breakdown and reconciliation
5. P2.5 — ADR-004: handling blocking tasks (comparison; spikes K1–K3 only)
6. P2.6 — Decision gate: apply `phase-2/plan.md` §7; record the Phase 3 choice

Phase 1 increments, in order (details in `phase-1/plan.md` §3):

1. ~~S0~~ ✓ DONE
2. ~~S1~~ ✓ DONE
3. ~~S2~~ ✓ DONE
4. ~~S3~~ ✓ DONE
5. ~~S4~~ ✓ DONE
6. ~~S5~~ ✓ DONE
7. ~~S6~~ ✓ DONE

Not queued (Phase 2 decides which comes first): per-worker queues and
work stealing; a mechanism for blocking tasks (suspension or an alternative,
per ADR-004); the dependency/fan-out benchmark (belongs to the blocking
track). Still open and not queued: backpressure, running-task cancellation,
default worker count.

Note: this list is intentionally short. Long speculative roadmaps belong
in `project-overview.md` §4 (vision) at most, not here — this section
should only ever list what's actually queued to start next.

## Blocked / unresolved

- Phase 2 sign-off decision 4 (Phase 3 decision rules, `phase-2/plan.md`
  §7) is pending. It does not block P2.5, but must be answered
  before any P2.2–P2.4 result is looked at. Rule 5 was reworded on
  2026-10-04 for the new primary environment (cloud container, M2
  secondary); the reworded text is part of what is to be signed off.
- Resolved 2026-10-04: how P2.2–P2.4 handle the M2's thermal throttling
  (Experiment 3). Owner decision: the Claude Code cloud container is the
  primary environment; M2 results are secondary and labelled as possibly
  thermally affected; no thermal guards added to the harness. Recorded in
  `phase-2/plan.md` §5 and §6 decision 3, `phase-2/scope.md` §3 items 1, 2
  and 8, `phase-2/implementation.md` §2.2.
- Open architectural questions (queue topology, task granularity,
  backpressure, blocking tasks) remain open in `architecture-context.md` §5.
  Phase 2 targets topology, granularity and blocking tasks.

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

### Experiment 2 — P2.1 reproduction of Experiment 1 on the ported script — 2026-10-04
Question: Did porting `cpu_saturation.py` onto `benchmarks/_harness.py` change what it measures?

Method: Experiment 1's two commands, repeated with the ported script and Experiment 1's method (3 recorded reps,
no warm-up), back to back:
`.venv/bin/python benchmarks/cpu_saturation.py --reps 3 --warmup 0 --json` (sweep: 10 / 1 / 0.1 ms;
T = 1, 2, 4, 8, 16) then
`.venv/bin/python benchmarks/cpu_saturation.py --with-processes --workers 4,8 --task-ms 1 --reps 3 --warmup 0 --work-seconds 3 --json` (control).
Reference: Experiment 1's printed per-row median wall and spread, recovered from the session record of the 2026-09-26
run (raw JSON was not kept). Pass condition (`phase-2/implementation.md` §3.1): `beyond_spread(new median, new
spread, Exp 1 median, Exp 1 spread)` false for every row. A second column normalizes the new median by the
measured task size (Exp 1 ÷ new, as printed by the script) to remove calibration differences between processes.
Environment: Apple M2 MacBook Air (Mac14,2, fanless; 4P + 4E, 8 logical CPUs), macOS 26.2 arm64, AC power, Low
Power Mode off, CPython 3.14.7 free-threaded (GIL disabled), Pyron 0.0.1-phase1, base commit `eede54b` + the
uncommitted P2.1 working tree; no third-party extension modules loaded. Calibration 29.8 ns/iter (sweep), 30.3
(control). Started 02:59:38 IST; sweep 2 min 43 s, control 28 s. Load average 4.5 before the start, mostly
other desktop apps.

Result:

| Run | Task | Kind | T | Exp 1 wall s (±%) | P2.1 wall s (±%) | diff | limit | result | diff, task-size normalized |
|---|---|---|---|---|---|---|---|---|---|
| sweep | 10 ms | serial | 1 | 3.039 (0.3) | 3.061 (1.0) | +0.7% | 1.0% | within | -0.0% within |
| sweep | 10 ms | raw | 1 | 3.076 (2.0) | 3.040 (1.7) | -1.2% | 2.0% | within | -1.9% within |
| sweep | 10 ms | raw | 2 | 1.584 (1.9) | 1.566 (0.1) | -1.1% | 1.9% | within | -1.9% within |
| sweep | 10 ms | raw | 4 | 0.890 (11.6) | 0.894 (4.8) | +0.4% | 11.6% | within | -0.3% within |
| sweep | 10 ms | raw | 8 | 0.823 (12.2) | 0.840 (13.2) | +2.0% | 13.2% | within | +1.3% within |
| sweep | 10 ms | raw | 16 | 0.819 (12.3) | 0.798 (9.4) | -2.5% | 12.3% | within | -3.2% within |
| sweep | 10 ms | pyron | 1 | 3.033 (2.4) | 3.064 (0.8) | +1.0% | 2.4% | within | +0.3% within |
| sweep | 10 ms | pyron | 2 | 1.575 (3.5) | 1.571 (1.5) | -0.3% | 3.5% | within | -1.0% within |
| sweep | 10 ms | pyron | 4 | 0.909 (7.1) | 0.912 (2.0) | +0.3% | 7.1% | within | -0.4% within |
| sweep | 10 ms | pyron | 8 | 0.848 (9.4) | 0.894 (17.5) | +5.4% | 17.5% | within | +4.6% within |
| sweep | 10 ms | pyron | 16 | 0.811 (10.4) | 0.758 (10.5) | -6.5% | 10.5% | within | -7.2% within |
| sweep | 1 ms | serial | 1 | 3.103 (5.9) | 3.195 (6.4) | +2.9% | 6.4% | within | -0.0% within |
| sweep | 1 ms | raw | 1 | 3.019 (0.3) | 3.081 (6.4) | +2.1% | 6.4% | within | -0.9% within |
| sweep | 1 ms | raw | 2 | 1.584 (1.0) | 1.609 (3.5) | +1.6% | 3.5% | within | -1.4% within |
| sweep | 1 ms | raw | 4 | 0.907 (1.6) | 0.927 (23.8) | +2.2% | 23.8% | within | -0.7% within |
| sweep | 1 ms | raw | 8 | 0.860 (17.4) | 0.744 (3.5) | -13.5% | 17.4% | within | -16.0% within |
| sweep | 1 ms | raw | 16 | 0.764 (2.3) | 0.805 (4.7) | +5.3% | 4.7% | **beyond** | +2.2% within |
| sweep | 1 ms | pyron | 1 | 3.032 (0.3) | 3.113 (7.4) | +2.7% | 7.4% | within | -0.3% within |
| sweep | 1 ms | pyron | 2 | 1.618 (2.6) | 1.629 (10.8) | +0.7% | 10.8% | within | -2.3% within |
| sweep | 1 ms | pyron | 4 | 0.940 (0.5) | 1.014 (10.5) | +7.9% | 10.5% | within | +4.7% within |
| sweep | 1 ms | pyron | 8 | 0.874 (18.9) | 0.761 (3.0) | -12.9% | 18.9% | within | -15.5% within |
| sweep | 1 ms | pyron | 16 | 0.786 (2.9) | 0.802 (6.7) | +2.0% | 6.7% | within | -1.0% within |
| sweep | 0.1 ms | serial | 1 | 3.079 (0.9) | 3.115 (6.4) | +1.2% | 6.4% | within | +0.2% within |
| sweep | 0.1 ms | raw | 1 | 3.020 (2.9) | 3.062 (1.9) | +1.4% | 2.9% | within | +0.4% within |
| sweep | 0.1 ms | raw | 2 | 1.605 (2.6) | 1.604 (1.3) | -0.1% | 2.6% | within | -1.0% within |
| sweep | 0.1 ms | raw | 4 | 0.911 (0.2) | 0.922 (1.6) | +1.2% | 1.6% | within | +0.2% within |
| sweep | 0.1 ms | raw | 8 | 0.738 (16.5) | 0.753 (5.2) | +2.0% | 16.5% | within | +1.0% within |
| sweep | 0.1 ms | raw | 16 | 0.800 (2.5) | 0.791 (3.3) | -1.1% | 3.3% | within | -2.1% within |
| sweep | 0.1 ms | pyron | 1 | 3.303 (0.3) | 3.301 (0.5) | -0.1% | 0.5% | within | -1.0% **beyond** |
| sweep | 0.1 ms | pyron | 2 | 1.745 (1.7) | 1.733 (0.6) | -0.7% | 1.7% | within | -1.7% within |
| sweep | 0.1 ms | pyron | 4 | 1.011 (1.9) | 1.021 (2.0) | +1.0% | 2.0% | within | +0.0% within |
| sweep | 0.1 ms | pyron | 8 | 0.795 (10.0) | 0.808 (7.3) | +1.7% | 10.0% | within | +0.7% within |
| sweep | 0.1 ms | pyron | 16 | 0.901 (1.6) | 0.895 (1.7) | -0.6% | 1.7% | within | -1.6% within |
| control | 1 ms | serial | 1 | 3.066 (1.1) | 3.144 (0.9) | +2.5% | 1.1% | **beyond** | -0.0% within |
| control | 1 ms | raw | 4 | 0.834 (5.6) | 0.918 (6.2) | +10.1% | 6.2% | **beyond** | +7.3% **beyond** |
| control | 1 ms | raw | 8 | 0.835 (0.6) | 0.894 (10.9) | +7.1% | 10.9% | within | +4.4% within |
| control | 1 ms | pyron | 4 | 0.870 (18.7) | 0.976 (10.8) | +12.2% | 18.7% | within | +9.4% within |
| control | 1 ms | pyron | 8 | 0.861 (4.0) | 0.924 (15.0) | +7.4% | 15.0% | within | +4.7% within |
| control | 1 ms | procs | 4 | 0.884 (8.0) | 0.962 (30.9) | +8.8% | 30.9% | within | +6.1% within |
| control | 1 ms | procs | 8 | 0.677 (6.5) | 0.696 (19.6) | +2.9% | 19.6% | within | +0.3% within |

- As measured: 37 of 40 rows within spread. Normalized for task size: 38 of 40; the control `serial` row's +2.5%
  is exactly the task-size difference (1.048 vs 1.022 ms per task). Normalization at 0.1 ms is limited by
  Experiment 1 printing the task size to 3 decimals (0.103 ms = ±0.5%), which is why `pyron` ×1 at 0.1 ms
  crosses its 0.5% limit only after normalization.
- The rows outside spread are `raw` and `serial` rows, which run code the port left AST-identical; no
  `pyron` row is outside spread as measured.
- Old/new A/B to isolate the port (original script from `eede54b` vs ported, alternated over 3 rounds, same
  commands): inconclusive twice; see Experiment 3.

Conclusion: The pass condition is **not fully met** (37/40). The evidence points to environment drift rather than the
port: the failing rows run unchanged code, one is fully explained by task size, and the remaining gap (control
`raw` ×4, +7.3% normalized against a 6.2% limit) is in a run that started right after 2 min 43 s of near-all-core
load on a fanless machine. That attribution rests on code identity, not on a successful A/B; the A/B could not
be run cleanly here.

Follow-up: the A/B was done on a cloud VM (Experiment 4). **Owner decision 2026-10-04: P2.1 accepted on Experiments 2
and 4** despite the 37/40 result.

### Experiment 3 — Thermal throttling of the test machine under sustained load — 2026-10-04
Question: Why did the old/new A/B for Experiment 2 give 40–100% spreads, and is calibration reliable on this machine?

Method: (a) the A/B itself: 12 fresh processes (old/new × sweep-16 / control × 3 rounds, alternating order), run
back to back after Experiment 2; each prints its calibration and measured task size. (b) Calibration probe:
`calibrate_ns_per_iter()` in fresh processes
(`cd benchmarks && ../.venv/bin/python -c "import _harness as h; print(h.calibrate_ns_per_iter())"`), 6× on an idle
machine, 6× while another process ran 4 threads of `burn`, then 8× (one every ~2 s) while another process ran 8 threads
of `burn` for 60 s, then 3× right after that load stopped. (c) A second A/B on the control command only, with a gate before
each run: wait until a fresh calibration is ≤ 31.5 ns. Same machine and session as Experiment 2, AC power.

Result:
- (a) 7 of 12 processes calibrated at 58.9–60.9 ns/iter instead of 29.6–31.3, so their "1 ms" task really measured
  0.70–0.99 ms; walls and spreads are not comparable.
- (b) Idle: 30.1–30.3 ns (6/6). 4 busy threads elsewhere: 33.6–35.5 ns. 8 busy threads elsewhere: 31.5, 36.9, 39.6,
  45.4, 49.5, 51.0, 74.2, 64.9 ns over ~30 s, rising steadily; right after the load stopped: 73.4, 61.1, 61.0 ns.
  `pmset -g therm` recorded no thermal or performance warning.
- (c) Every gated run calibrated at 29.5–30.4 ns after ≤ 16 s of waiting, but measured task sizes were 1.07–1.36 ms,
  run spreads 26–82%, and every multi-thread row was 39–80% slower than Experiment 1 (`serial` 7–16%), for both scripts. Old vs new: no row beyond
  spread, which says nothing at these spreads.

Conclusion: This fanless M2 throttles within tens of seconds of all-core load and stays throttled after the load ends.
A short single-thread calibration can read "cool" while sustained throughput is still degraded, so the calibration gate in
(c) did not work. Calibration slowing under load and recovering only slowly fits thermal throttling better than
efficiency-core placement (it stays slow with the machine idle), but placement was not ruled out directly. Consequences:
(1) run-to-run spread on this machine is partly thermal, not only noise, and the size and order of a sweep change its results;
(2) per-process calibration can silently change the task size between runs; (3) the A/B that would have confirmed
Experiment 2 could not be run cleanly. Hypothesis, untested: part of Experiment 1's up-to-19% spread at 8+ threads was
thermal.

Follow-up: resolved 2026-10-04 — P2.2–P2.4 run primarily on the Claude Code cloud container; the M2 is secondary
(`phase-2/plan.md` §6 decision 3).

### Experiment 4 — P2.1 old/new A/B and 0.1 ms check on a cloud VM — 2026-10-04
Question: Does the ported `cpu_saturation.py` measure the same thing as the original (`eede54b`), judged by an
alternated old/new A/B on one machine? (The A/B that Experiment 2 could not complete because of thermal throttling,
Experiment 3.) Is the small 0.1 ms slowdown seen in the first A/B real?

Method: Four steps on one machine, in this order.
(a) Test suite: `pytest` on the harness branch at `41af772` (and on `development`'s 160 tests before it).
(b) One old/new pair, **not alternated** (new script first, then old): the sweep (10 / 1 / 0.1 ms; T = 1, 2, 4, 8,
16) and the control (`--with-processes --workers 4,8 --task-ms 1 --work-seconds 3`), 3 repetitions each, ported script
with `--warmup 0`.
(c) Four alternated rounds (old→new, new→old, old→new, new→old) of the same sweep + control commands, fresh process per
run, same flags.
(d) Six alternated rounds of the sweep restricted to `--task-ms 0.1 --workers 1,2,4,8,16 --reps 3`.
Comparison in (c) and (d): per row, median wall over the rounds for each variant, **normalized by that process's
measured task size** (removes per-process calibration drift, Finding 2026-10-04), and the raw median ratio. "Noise
floor" = the larger of the two variants' between-round spread, (max − min) / median over the rounds. This is **looser
than the plan's pass condition** (`beyond_spread`, which uses the within-run spread of 3 repetitions), so "within" here
is a weaker statement than in Experiment 2. The analysis scripts and every raw output were kept in the session
scratchpad only (not committed, per sign-off decision 2 in `phase-2/plan.md` §6).
Environment: cloud container (Linux 6.18.44-fc-v64, x86_64), Intel Xeon @ 2.10 GHz, 4 logical CPUs, all with the same
`cpu_capacity` (1024; no performance/efficiency split), no governor or power information exposed; whether the
vCPUs are dedicated or shared with other tenants is not known. CPython **3.14.0rc2** free-threaded (GIL disabled,
installed with `uv`; Experiments 1–3 used 3.14.7), Pyron 0.0.1-phase1; ported script at `41af772` (clean tree),
original at `eede54b`. Calibration 34.5–40.4 ns/iter across processes. Started 22:30 UTC, finished 23:30 UTC on 2026-10-03 (04:00–05:00 IST on
2026-10-04, after Experiments 2–3).

Result:
- (a) Full suite on `41af772`: **196 passed** in 8.1 s (160 runtime + 36 harness tests). On `development`: 160
  passed in 7.2 s.
- (b) As measured, 6 of 40 rows within the larger of the two within-run spreads; normalized by measured task size, 36 of
  40. The ported script's `serial` rows were +11–12% slower in the sweep, and equal after normalizing (0.0%): the
  as-measured gap was calibration drift between processes (1.010 vs 1.121 ms measured at "1 ms"), not the port. The
  order was not alternated, so any drift or heat between the two halves is confounded with the variant.
- (c) Median-of-rounds, normalized: **39 of 40 rows within the noise floor**; as-measured 3 of 40 beyond. `serial` rows
  differ by 0.0–0.4%. The one row beyond: Pyron ×4, 0.1 ms, +4.4% against a 4.2% floor (all four rounds slower:
  +1.7, +4.3, +5.6, +4.3%). A +2% shift on the 0.1 ms `raw` rows in (c) did not repeat in (d).
- (d) Pooled paired differences (new vs old in the same round, normalized): `serial` +0.02% (n = 6); `raw` +0.3% mean,
  +0.2% median (n = 30, stdev 2.5%); **`pyron` +2.2% mean, +3.2% median (n = 30, stdev 3.6%)**. Per Pyron row: +1.3%
  (T=1), +2.2% (T=2), +4.5% (T=4), +4.1% (T=8, slower in 5 of 6 rounds), +2.0% (T=16). No single row beyond its noise
  floor (Pyron rows' floors 6.8–10.7%). The rows are not independent (same rounds, same machine state), so the pooled
  figure has no meaningful p-value.
- Incidental, from the ported script's one non-alternated sweep in (b) (one run, 3 repetitions, spread 0.7–10.6%):
  Pyron ÷ raw throughput at ≥ 4 workers was 96–101% at 10 ms, 98–102% at 1 ms and 78–92% at 0.1 ms (falling with
  worker count: 92% at 4, 83% at 8, 78% at 16 on 4 CPUs); at 0.1 ms, 1 worker, Pyron's kernel-time share was 10.4%
  vs 0.0% for `raw`. `raw` threads reached 3.8–3.9× speedup on 4 CPUs at 4+ threads (efficiency 94–99%) at every task size.

Conclusion: The port does not change what the `serial` and `raw` paths measure on this machine (differences ≤ ~0.4%
pooled, inside the noise). On the Pyron path at 0.1 ms the ported script reads ≈ 2–3% slower, in the direction
of making Pyron look worse; the measured `run_pyron` body is textually identical in both scripts (apart from helper
names), so this is **unexplained**. Candidates, none isolated: the harness's `faulthandler` watchdog armed around every
run (`dump_traceback_later`), the different module layout. A 2% bias is small next to the 8–22% Pyron-vs-raw gap at
0.1 ms but is not nothing for P2.3. Limits: one cloud VM with unknown tenancy, an RC interpreter build, 4–6 rounds,
a noise floor looser than the plan's, and a procedure that differs from the one the owner specified under Blocked /
unresolved (option 3: three rounds, a ≤ 31.5 ns calibration gate and idle period before each run, the control and
`--workers 16 --task-ms 1` commands) — no gate was used because its threshold was set for the M2. This experiment
therefore **does not by itself discharge the owner decision**, and the plan's literal pass condition (against
Experiment 1's M2 numbers) was not applied.

Follow-up: (1) ~~owner decision on P2.1~~ — **accepted on this evidence, 2026-10-04**; whether a cooled / cloud machine
becomes the primary environment for P2.2–P2.4 — **yes: the Claude Code cloud container, decided 2026-10-04**. (2) Optional, ≈ 10 min: A/B of the
ported script with and without the watchdog at 0.1 ms to test the one named candidate; worth doing if the Phase 3
decision rules (§7, unsigned) turn out to be tight. (3) If a cloud VM is used for later experiments, pin the
interpreter to 3.14.7 or record the version difference with every result.

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

- 2026-10-04 (P2.1) — **The test machine throttles under sustained all-core load** (Experiment 3): calibration went from
  ~30 to ~60–74 ns/iter within ~30 s of 8-thread load and stayed there after the load ended. Phase 2's measurement plan
  did not account for this; see Blocked / unresolved.
- 2026-10-04 (P2.1) — **Calibration is per process and can drift between runs**, so the same `--task-ms` can mean a
  different amount of work in two processes (2.5% between Experiment 1 and 2 at 1 ms; up to ~30% under heat). Compare
  measured task sizes (printed per table) before comparing walls across processes.

- 2026-10-04 (P2.1) — **On a homogeneous 4-core VM, raw threads reach 3.8–3.9× on 4 CPUs (94–99% efficiency)**
  (Experiment 4, one run). Experiment 1's 3.4–4.2× ceiling at 8+ threads on the M2 therefore reflects the mixed
  4P+4E hardware at least in part, rather than only the interpreter; this is Experiment 1's "repeat on a
  homogeneous-core machine" follow-up, for one VM and an RC build only. The Pyron-vs-raw gap at 0.1 ms (78–92%)
  remains and grows with worker count, consistent with Experiment 1.
- 2026-10-04 (P2.1) — **Open: the ported script reads ≈ 2–3% slower on the Pyron path at 0.1 ms** (Experiment 4 (d)),
  not on `raw` or `serial`. Cause not isolated (watchdog and module layout are candidates). Treat as a known
  bias against Pyron of that size in P2.3 until tested.
- 2026-10-04 (P2.1) — Per-process calibration also drifts on the cloud VM (34.5–40.4 ns/iter, ±8%), so the same
  as-measured vs normalized gap (e.g. +11–12% on the `serial` row) appears there without any throttling signature
  in the `serial` rows. Always compare normalized walls across processes.

*(further findings — populated as experiments produce results, including negative
or inconclusive ones)*

## Validation status

Full suite: 196 tests passing — 160 runtime tests (S0–S6) + 36 benchmark-harness
tests — no warnings (2026-10-04, free-threaded CPython 3.14.7, GIL disabled —
asserted by `tests/conftest.py`).
Per component (S0–S6): tested as listed under Implementation progress.
Cloud run (2026-10-04, Linux x86_64, CPython 3.14.0rc2 free-threaded, GIL disabled): the same 196 tests passed
in 8.1 s at `41af772`, and `development`'s 160 in 7.2 s (Experiment 4 (a)).
Known-untested: runs longer than seconds (no hours-long soak); other
platforms and Python versions (only macOS / Darwin 3.14.7t, plus one Linux
x86_64 VM on 3.14.0rc2 for a single suite run); resource
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
| 2026-09-26 | Added `benchmarks/cpu_saturation.py` (standalone CPU-utilisation/scaling benchmark; no `pyron/` changes) and recorded Experiment 1. Updated stale "no benchmark" statements here, in `README.md` and in `architecture-context.md` §5. Script committed in `a8aa63d` and merged to `development` via PR #2. | Claude Sonnet 5 |
| 2026-10-04 | Corrected the 2026-09-26 benchmark entry: the script is committed (`a8aa63d`) and merged to `development` (PR #2), not uncommitted. Re-ran full suite on `development`: 160 passing. Documentation only. | Claude Opus 5.5 |
| 2026-10-04 | Wrote the Phase 2 plan (`context/phase-2/`: plan, scope, implementation, verification) from the owner's draft list, restructured as "measure, then decide"; moved current phase to Phase 2 (planned). Recorded sign-off decisions 1–3; decision 4 (Phase 3 decision rules) pending. Updated `AGENTS.md` summary. Documentation only, no code. | Claude Opus 5.5 |
| 2026-10-04 | **P2.1 started**: added `benchmarks/_harness.py` (moved workload/timing/environment code unchanged; generalized samples and statistics; extended environment; GIL re-check after every run; beyond-spread test; shared flags; JSON default folder; hang watchdog) and ported `benchmarks/cpu_saturation.py` onto it (measured run bodies unchanged; defaults now 5 reps + 1 warm-up). `tests/test_bench_harness.py` (36 tests); 196 passing. `benchmarks/results/` git-ignored. Corrected `phase-2/implementation.md` §3.1: Experiment 1 was two commands (default sweep + separate process control). Updated README, AGENTS.md, phase-2 status headers. No `pyron/` changes. Reproduction run pending. | Claude Opus 5.5 |
| 2026-10-04 | **P2.1 reproduction run** (Experiment 2): 37/40 rows within spread; failing rows all in unchanged code. Two old/new A/B attempts spoiled by thermal throttling; probe recorded as Experiment 3. Added two findings and a blocking owner decision (accept P2.1 + add thermal guards / cooled primary machine / re-run after long idle). P2.1 not marked complete. No `pyron/` changes. | Claude Opus 5.5 |
| 2026-10-04 | Recorded **Experiment 4** (P2.1 old/new A/B on a 4-vCPU Linux cloud VM, CPython 3.14.0rc2): 39/40 rows within the noise floor normalized; `serial`/`raw` paths unchanged; unexplained ≈ +2–3% on the Pyron path at 0.1 ms. Added three findings, a status note under Blocked / unresolved and the cloud suite run under Validation status. Dates normalized to local (IST) from the session's UTC container clock. P2.1 not marked complete; owner decision still pending. Documentation only. | Claude Sonnet 5.5 (cloud session); applied by Claude Opus 5.5 |
| 2026-10-04 | **P2.1 Complete**: owner accepted P2.1 on the evidence of Experiments 2 (37/40) and 4 (39/40, `serial`/`raw` unchanged); the Pyron-path ≈ 2–3% bias at 0.1 ms stays an open finding. Moved P2.1 to Completed (also added the missing S6 row); narrowed Blocked / unresolved to the thermal-handling decision for P2.2–P2.4 plus decision 4; updated Experiment 2–4 follow-ups. Amended `phase-2/scope.md` §3 limitation 8 and added a thermal row to `phase-2/plan.md` §5; updated status headers in `phase-2/` and `AGENTS.md`. Full suite re-run: 196 passing. Documentation only, no code. | Claude Opus 5.5 |
| 2026-10-04 | Owner decision: the **Claude Code cloud container is the primary benchmark environment for P2.2–P2.4**; the M2 is secondary (its results labelled as possibly thermally affected); no thermal guards added. Amended `phase-2/plan.md` §5 (noise and thermal rows), §6 decision 3, §7 rule 5 (reworded for the new primary; still pending sign-off with decision 4); `phase-2/scope.md` §1 and §3 items 1, 2, 8; `phase-2/implementation.md` §2.2. Removed the thermal item from Blocked / unresolved; decision 4 is the only gate before P2.2. Documentation only. | Claude Opus 5.5 |
