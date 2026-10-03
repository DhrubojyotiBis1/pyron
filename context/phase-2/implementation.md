# Phase 2 — Implementation Design

> Status: PLANNED — not started. Last updated: 2026-10-04.
> This is the design of the measuring tools, the experiments and ADR-004.
> Evidence of implementation will be in the committed scripts and in
> `../progress-tracker.md`, not in this document. Nothing here changes
> `pyron/`.

## 1. Entities

Phase 2 builds measuring tools, not runtime components. The harness is a
plain module of functions and small data classes; each benchmark is a
script that composes them.

| Entity | Kind | Responsibility | Origin |
|---|---|---|---|
| `environment()` | function | Record interpreter, build, GIL state, OS, CPU model, core counts and types, power, git commit and dirty flag, date | Extracted from `cpu_saturation.py`, extended for Linux core types |
| `require_free_threading()` | function | Refuse to run with the GIL enabled unless explicitly allowed; re-checkable after imports | Extracted (`gil_enabled` + the refusal in `main`) |
| `burn`, `calibrate_ns_per_iter` | functions | Calibrated pure-Python CPU work touching only locals | Extracted unchanged |
| `Window` | context manager | Wall time and process CPU time (user, sys) around a block | Extracted unchanged |
| `Sample` | data class | One timed run: variant, configuration, wall, user, sys, threads used, extra metrics | Extracted, generalized (configuration as a mapping) |
| `summarize()` / `Stats` | function / data class | Median, spread ((max − min) / median), min, max over repetitions | Extracted, generalized |
| `write_json()` | function | Environment + every raw sample to a path; default folder git-ignored | Extracted |
| `common_args()` | function | Shared command-line flags (§2.7) | New |
| `run_threads()` | function | Start K threads behind a barrier, join with a timeout, fail loudly on a hang | New (replaces repeated inline code) |

Benchmark scripts (one question each):

| Script | Increment | Question |
|---|---|---|
| `benchmarks/cpu_saturation.py` | P2.1, P2.3 | How much CPU does `Runtime` keep busy, and at what cost per task, vs raw threads and `ThreadPoolExecutor`? |
| `benchmarks/scheduler_contention.py` | P2.2 | What does the global queue cost under contention, and what is the most sharding could save? |
| `benchmarks/task_cost.py` | P2.4 | Where does the per-task cost go? |

## 2. Harness design (P2.1)

### 2.1 Extraction rule

Move code, do not rewrite it. Functions that already produced Experiment 1
are moved verbatim where possible, so the reproduction run (§3.1) tests the
move rather than a new implementation. Any behavioural change to an
extracted function is a separate, recorded change.

### 2.2 Environment and portability

- Everything `cpu_saturation.py` records today, plus:
  - usable CPUs from `os.process_cpu_count()` (respects affinity) next to
    `os.cpu_count()`;
  - core types: on macOS the existing `hw.perflevel*` counts; on Linux the
    distinct values of `/sys/devices/system/cpu/cpu*/cpu_capacity` or
    maximum frequency, if present, and the CPU frequency governor;
  - the list of imported third-party extension modules, so a later reader
    can see what was loaded.
- Every lookup is optional: a missing file or command records `None` and
  never fails the run. The harness must run unchanged on Linux and macOS
  (`plan.md` §6 decision 3).

### 2.3 GIL guard

- Checked at start-up, as today, **and** again after all imports and at the
  end of each run. On a free-threaded build, importing an extension module
  that does not declare free-threading support re-enables the GIL, so a
  start-up check alone is not enough.
- `--allow-gil` keeps today's meaning: run anyway, label the output as a
  GIL-enabled control.

### 2.4 Workload

`burn` and its calibration are unchanged. Task sizes are expressed in
milliseconds of calibrated serial work, as today. An **empty task** (zero
iterations) is added so per-task overhead can be measured with no work at
all.

### 2.5 Measurement and statistics

- One unrecorded warm-up repetition per configuration, then N recorded
  repetitions (default 5 in Phase 2, up from 3 in Experiment 1, because of
  the recorded noise).
- `gc.collect()` before each window; GC stays enabled during it (as in
  Experiment 1).
- Report per configuration: median, spread, min and max of wall time, and
  the derived metrics. Raw per-repetition samples go to JSON.
- "Beyond spread" (used by `plan.md` §7) is computed by the reporting code,
  not judged by eye.

### 2.6 Output

- Console: a fixed-width table per script, with the environment block
  first.
- `--json PATH`: environment and every raw sample. Default folder
  `benchmarks/results/`, added to `.gitignore` in P2.1. Raw JSON is not
  committed (`plan.md` §6 decision 2); the tracker records the summary
  table, the exact command and the environment.

### 2.7 Command-line conventions (every script)

| Flag | Meaning |
|---|---|
| `--quick` | Smoke run: seconds, minimal configurations; proves the script works, produces no reportable numbers |
| `--reps N` | Recorded repetitions per configuration |
| `--json PATH` | Write raw samples |
| `--allow-gil` | Control run with the GIL enabled |
| script-specific axes | Comma-separated lists, e.g. `--workers 1,2,4,8` |

### 2.8 Validity rules (every script)

- Every task or item result is verified; a wrong or missing result fails
  the run, it is never reported.
- The number of distinct threads that did work is counted and reported.
- Threads are started behind a barrier and joined with a timeout; a hang
  fails the run.
- No benchmark relies on the GIL for atomicity: shared counters and result
  collection use locks or single-owner lists merged after join (§5).

## 3. Experiment designs

### 3.1 P2.1 — Reproduction run

- Command: `cpu_saturation.py` with Experiment 1's configuration (task sizes
  10 / 1 / 0.1 ms; workers 1, 2, 4, 8, 16; `--with-processes`), on the same
  machine, after the port.
- Pass condition: for each row, the new median wall time lies within the
  larger of the two recorded spreads of Experiment 1's median. A row
  outside it is investigated before any Phase 2 benchmark is trusted.
- Recorded as its own experiment (it is a re-run, and re-runs are evidence).

### 3.2 P2.2 — Scheduler contention

**Question:** What does `GlobalQueueScheduler` cost per item under
contention, and how much would a sharded layout save at most?

**Variants** (all carry the same pre-built `Task` objects with a no-op
callable; consumers count and record items but do not run them):

| Id | Variant | Why it is here |
|---|---|---|
| G | `pyron.scheduler.GlobalQueueScheduler` (`submit` / `next_task` / `close`) | The thing being measured |
| D | Bare `collections.deque` + one `threading.Condition`, same algorithm, no closed-flag handling | Isolates the cost of Pyron's wrapper and close checks |
| Q | `queue.SimpleQueue` with one sentinel per consumer | The best single shared queue in the standard library |
| S | Sharded upper bound: one deque + lock + condition per consumer, producers place items round-robin, each consumer reads only its own shard, one sentinel per shard | Best case for per-worker queues. No stealing, no close atomicity, no idle parking (`scope.md` §3.6) |

**Modes:**

- *Saturated*: the queue is filled before the window opens, then C
  consumers drain it. Measures fetch contention with no blocking waits.
- *Streaming*: P producers and C consumers run concurrently. Includes
  blocking waits and wake-ups.
- *Hand-off latency*: two threads ping-pong one item through a pair of
  instances of each variant. Half the round trip is the cost of waking an
  idle consumer. Reported as median and 90th percentile over many trips.

**Axes:** consumers C ∈ {1, 2, 4, 8, ncpu, 2·ncpu}; producers P ∈ {1, 2, 4}
(streaming only); items per run sized so each run lasts at least one second.

**Metrics:** items per second, nanoseconds per item, process CPU time, sys
share, spread.

**Validity:** each consumer records the ids it received in its own list;
after join, the union must equal the submitted set with no duplicates.

**Feeds:** `plan.md` §7 rule 1 (first clause: S vs G, streaming, C ≥ 4) and
P2.4 (contended lock cost, hand-off latency).

### 3.3 P2.3 — End-to-end baseline

**Question:** How does `Runtime`'s per-task cost compare with
`ThreadPoolExecutor` and raw threads, across task sizes and producer
counts? What task size is needed before overhead stops mattering?

**Implementation:** extend `cpu_saturation.py` rather than writing a new
script, because the question and the workload are the same. Additions are
opt-in, so the default configuration still reproduces Experiment 1:

- `tpe` variant behind `--with-tpe`: `ThreadPoolExecutor(max_workers=T)`,
  tasks submitted from the producer thread(s), awaited through their
  futures.
- Smaller task sizes (0.03 and 0.01 ms) and the empty task, via
  `--task-ms`.
- `--producers` for `tpe` as well as `pyron` (both accept submissions from
  several threads; `raw` has no producer).

**Axes:** task sizes {10, 1, 0.1, 0.03, 0.01 ms, empty}; workers {1, 2, 4,
8, ncpu, 2·ncpu}; producers {1, 4}.

**Derived metrics:**

- Per-task overhead at T = 1: (variant wall − serial wall) / tasks.
- Granularity point (reporting definition, not a claim): the smallest
  measured task size at which `pyron` reaches at least 90% of `raw`
  throughput at T = ncpu. Recorded per producer count.

**Validity:** every result verified; distinct worker threads counted;
spread reported.

**Feeds:** `plan.md` §7 rule 3 (`tpe` vs `pyron` overhead), the end-to-end
per-task figure that P2.4 reconciles against, and an annotation on the
"task granularity" open question in `architecture-context.md` §5.

### 3.4 P2.4 — Per-task cost breakdown

**Question:** Of Pyron's per-task overhead, how much is the scheduler lock,
how much is thread wake-up, and how much is everything else?

**Component timings** (single thread, timed in batches of many operations
because each is sub-microsecond; median over repetitions):

| # | Step | Measured as |
|---|---|---|
| C1 | `Task` construction (lock, event, fields) | Construct a batch of tasks |
| C2 | `TaskHandle` construction | Wrap a batch of tasks |
| C3 | `submit` with no waiting consumer | Submit a batch to a fresh `GlobalQueueScheduler` |
| C4 | `next_task` with items ready | Fetch the same batch back |
| C5 | `Task.run` with a no-op callable (claim, two transitions, event set) | Run a batch of pending tasks |
| C6 | `TaskHandle.result()` on a completed task | Read a batch of results |
| C7 | `Runtime.spawn` (cross-check; includes C1–C3 and lifecycle checks) | Spawn a batch into a started one-worker runtime whose worker is held by a blocker task waiting on an event |

**Lock share:** C3 + C4 minus the same deque operations with no lock gives
the uncontended lock cost. P2.2's saturated mode at C = T minus the
uncontended figure gives the added cost of contention.

**Wake-up share:**

- P2.2's hand-off latency gives the cost of one wake-up.
- End-to-end, a *prefilled* variant (every worker is first held by a
  blocker task waiting on an event, all tasks are spawned, then the
  blockers are released, so workers never sleep) is compared with
  the normal streamed variant at the same configuration. The difference in
  wall time and in sys share is attributed to wake-ups and producer
  interaction. This directly tests Experiment 1's hypothesis about the
  higher kernel-time share.

**Reconciliation:** the sum of C1–C6 (plus lock contention and wake-ups
where they apply) is compared with P2.3's per-task overhead at T = 1 for the
empty task and for 0.1 ms. The unexplained remainder is reported as a
number, not hidden.

**Sampling profiler (optional):** if a sampling profiler is confirmed to work
on free-threaded 3.14, run it on the P2.3 empty-task configuration and record
the top frames. Installed into the local virtual environment only; it is not
added to project dependencies without owner approval. `cProfile` is not
used for multi-threaded attribution.

**Internal APIs:** P2.4 constructs `Task` and drives `GlobalQueueScheduler`
directly. That is acceptable for a benchmark; it does not make those APIs
public.

**Feeds:** `plan.md` §7 rule 1 (second clause) and rule 3.

## 4. ADR-004 — structure (P2.5)

Written into `architecture-context.md` §8 as
`ADR-004 — Handling blocking tasks — PROPOSED — <date>`, then `DECIDED` on
owner sign-off. It does not change ADR-001..003; it states which of them a
later implementation would have to supersede.

### 4.1 Problem and evidence

The demonstrated deadlock (`TestDocumentedLimitation` in
`tests/test_s6_stress.py`): with N workers each running a task that waits
on a queued task's result, no progress is made until a wait times out.

### 4.2 Scope decision (decided first, because it constrains the rest)

| Scope | Covers |
|---|---|
| B1 | A task waiting on another task's result (`TaskHandle.result()` from a worker) |
| B2 | B1 plus waits on Pyron-provided primitives (for example channels or events) |
| B3 | Any blocking: foreign locks, I/O, sleep |

### 4.3 Options

| Id | Option | One-line description |
|---|---|---|
| O1 | Generator / coroutine tasks | Tasks `yield` or `await` at wait points; a suspended task returns its worker and is resubmitted when woken |
| O2 | greenlet | Stackful switching without changing user function syntax |
| O3 | Spare (compensating) threads | When a task blocks in a known wait, the runtime starts or wakes an extra worker so N workers stay runnable |
| O4 | Run-while-waiting | A worker waiting on a task runs queued tasks itself, preferably the awaited one, instead of blocking |
| O5 | Detection only | Detect the all-workers-waiting state and fail loudly instead of hanging |
| O6 | Status quo | Keep the documented limitation |

### 4.4 Criteria (every option scored on every criterion)

1. Which scopes (B1–B3) it covers.
2. Effect on the user-facing API (does user code have to change form?).
3. Which `CONFIRMED` ADRs it would supersede: ADR-001 (states, plain
   callable), ADR-002 (Scheduler contract, e.g. a resubmit path), ADR-003
   (lifecycle and shutdown).
4. Fit with per-worker queues and stealing (where does a woken task go?).
5. Cancellation and shutdown semantics: what happens to a suspended or
   waiting task on `cancel()` and on drain-mode shutdown (which must not
   hang).
6. Compatibility with "Python-first" and with free-threaded CPython
   (`architecture-context.md` §4).
7. Effect on the thread count (does N stay fixed? bounded?).
8. Implementation and verification risk.
9. Closeness to the project's Go-inspired direction
   (`project-overview.md` §4).

### 4.5 Spikes (one factual question each; `spikes/`, labelled `EXPERIMENTAL`)

| Id | Question | Informs |
|---|---|---|
| K1 | Does greenlet install and import on free-threaded 3.14 **without re-enabling the GIL**, and can a greenlet be resumed on a different thread from the one that created it? | O2, criteria 4 and 6 |
| K2 | How deep can run-while-waiting nest on a worker thread before hitting the recursion limit or the thread stack size, and is the stack size adjustable from Python? | O4, criterion 8 |
| K3 | What does starting a thread on demand cost on this machine (start latency, median and 90th percentile)? | O3, criterion 7 |

Each spike is recorded as an experiment in the tracker, whatever its
outcome. Further spikes are added only for a factual question the ADR
cannot answer otherwise, and are listed here when added.

### 4.6 Output

A recommendation (an option and a scope), its consequences for ADR-001..003,
what Phase 3 or 4 would build if the blocking track is chosen, and a sketch
of how it would be verified (including the dependency/fan-out benchmark from
`plan.md` §8).

## 5. Ownership and synchronization in benchmark code

Benchmarks are concurrent programs too; a racy benchmark produces wrong
numbers silently (`coding-standards.md` §3–§4).

| State | Owner | Who may mutate | Protection |
|---|---|---|---|
| Per-thread result list (ids received, results computed) | The thread that appends to it | That thread only | Single owner; read by the main thread only after join |
| Raw-thread work counter (existing `raw` variant) | Benchmark run | All raw worker threads | One lock (unchanged from `cpu_saturation.py`) |
| Sharded-queue shard (variant S) | Its consumer's shard | Producers (append), its consumer (pop) | One lock + condition per shard |
| Start barrier | Benchmark run | All participating threads | `threading.Barrier` |
| Samples and stats | Main thread | Main thread only | Single owner |

No spin loops; every wait is a blocking primitive; every join has a timeout.

## 6. File layout (proposed; finalized in P2.1 and recorded in the tracker)

| Path | Contents |
|---|---|
| `benchmarks/_harness.py` | Shared harness (§1, §2) |
| `benchmarks/cpu_saturation.py` | Ported in P2.1; extended in P2.3 |
| `benchmarks/scheduler_contention.py` | P2.2 |
| `benchmarks/task_cost.py` | P2.4 |
| `benchmarks/results/` | Raw JSON, git-ignored |
| `spikes/` | P2.5 spikes, each with an `EXPERIMENTAL:` module docstring; never imported by `pyron/`, never run by pytest |
| `tests/test_bench_harness.py` | Unit tests for the harness's pure helpers |

## 7. Documentation obligations

- Every script's module docstring states: the question, how to run it,
  what each metric means, and its caveats (as `cpu_saturation.py` does
  today).
- Type hints on every function.
- No performance claims in code comments (`coding-standards.md` §11).
- Each increment updates `../progress-tracker.md` in the same change.
