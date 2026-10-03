# Phase 2 — Scope

> Status: IN PROGRESS (P2.1). Scope unchanged. Last updated: 2026-10-04.
> Scope changes for this phase must be flagged and recorded here, not
> absorbed silently (`ai-workflow-rules.md` §2).

## 1. In scope

- **A shared benchmark harness** under `benchmarks/`, extracted from
  `benchmarks/cpu_saturation.py`: environment recording, GIL guard,
  calibrated CPU workload, timing and CPU-time sampling, repetitions with
  median and spread, result verification, JSON output, command-line
  conventions. `cpu_saturation.py` is ported onto it.
- **Portability of the harness** to Linux and macOS, so the owner can run it
  unchanged on a homogeneous-core machine (`plan.md` §6 decision 3).
- **Three measurement increments** (P2.2–P2.4), each a committed script and
  a recorded experiment:
  - the scheduler alone under contention, with comparison queues and a
    throwaway sharded-queue upper bound;
  - end-to-end `Runtime` vs `ThreadPoolExecutor` vs raw threads across task
    sizes and producer counts;
  - a per-task cost breakdown reconciled against the end-to-end figure.
- **ADR-004** on handling blocking tasks: scope of "blocking", options,
  evaluation against fixed criteria, recommendation. Written `PROPOSED`;
  becomes `DECIDED` on owner sign-off.
- **Throwaway spikes** that answer a single factual question for ADR-004
  (for example: does greenlet import on free-threaded 3.14 without
  re-enabling the GIL?). They live outside `pyron/` and are labelled
  `EXPERIMENTAL`.
- **Small unit tests for the harness's pure helpers** (statistics,
  environment parsing). These test the measuring tool; they do not run
  benchmarks, so they may live in `tests/` (`coding-standards.md` §10).
- **Recording**: every experiment in `../progress-tracker.md`, win, lose or
  inconclusive; raw JSON written to a git-ignored folder and not committed
  (`plan.md` §6 decision 2).
- **The decision gate** (`plan.md` §7) and the recorded Phase 3 choice.

## 2. Out of scope

| Item | Why | Where it is tracked |
|---|---|---|
| Any change to `pyron/` (features, fixes, refactors, instrumentation) | Phase 2 measures the Phase 1 runtime as it is; changing it would move the baseline | Phase 3 onwards |
| Per-worker queues / work stealing in `pyron/` | Whether to build them is what this phase decides. The sharded queue in P2.2 is a benchmark-only upper bound, not a scheduler | `architecture-context.md` §5 (queue topology); Phase 3 candidate |
| Suspension, a `WAITING` state, wake-up/continuation scheduling | ADR-004 decides the approach on paper; building it is Phase 3 or 4 | `architecture-context.md` §5 (task representation, blocking tasks) |
| Dependency / fan-out benchmark | Needs the waiting mechanism ADR-004 chooses | `plan.md` §8 |
| Fixing any overhead the measurements find | Recorded as a finding and, if rule 3 fires, queued for Phase 3 | `plan.md` §7 |
| Committing raw benchmark JSON | Owner decision (`plan.md` §6 decision 2) | — |
| Benchmarks in the normal pytest run | Slow and noisy by nature | `coding-standards.md` §10 |
| CI, benchmark dashboards, regression tracking over time | Not needed to make the Phase 3 decision | Not queued |
| Comparisons with `multiprocessing` beyond the existing `--with-processes` control | Experiment 1 already has the control; a fuller study does not affect the Phase 3 choice | `project-overview.md` §8 |
| Backpressure, running-task cancellation, default worker count | Separate open questions | `architecture-context.md` §5 |
| `asyncio` integration | Out of project scope initially; ADR-004 may discuss coroutine tasks but does not adopt asyncio | `project-overview.md` §7 |
| C extensions written by this project | Project constraint | `architecture-context.md` §4 |

## 3. Known limitations of the Phase 2 approach

These are accepted limits on what Phase 2's evidence can show. Each is to
be stated in the experiment record it affects.

1. **One machine in this phase's own runs.** The planned runs are on the
   Apple M2 (4 performance + 4 efficiency cores). Results do not generalize
   to other hardware, operating systems or Python builds. Homogeneous-core
   runs depend on the owner and are not guaranteed by the end of the phase.
2. **Heterogeneous cores blur scaling.** A thread that lands on an
   efficiency core finishes later regardless of the scheduler. Effects seen
   equally with raw threads are not attributed to Pyron.
3. **Noise.** Experiment 1's spread at 8+ threads (up to 19%) means
   differences of a few percent are not distinguishable. Phase 2 can show
   large effects or their absence, not small ones.
4. **Micro-measurements may not add up.** Timing each step of a task's life
   in isolation removes cache, contention and scheduling interactions that
   exist end to end. P2.4 reports the gap; it does not explain it away.
5. **Timer and profiler limits.** Python-level timing has non-trivial
   overhead at the sub-microsecond scale, so the cheapest steps are timed
   in batches. A sampling profiler may not support free-threaded 3.14; if
   none does, P2.4 relies on component timing alone. `cProfile` is not used
   to attribute multi-threaded cost.
6. **The sharded queue is an upper bound, not a design.** It has no
   stealing, no close/submit atomicity and no idle-worker parking. A real
   work-stealing scheduler would recover less than it shows, never more.
7. **ADR-004 is paper evidence.** Apart from spikes answering single
   factual questions, no option is implemented, so the ADR's risk
   assessments are reasoned, not measured.
8. **Short runs only.** Runs last seconds to minutes. Thermal throttling and
   long-running behaviour are not covered unless a run is explicitly made
   long and recorded as such.
9. **Phase 1 limitations still stand.** Nothing in `../phase-1/scope.md` §3
   is fixed by this phase.

## 4. Scope-change rule

If a measurement shows something that seems to demand a code change (for
example, an obvious overhead in `pyron/`), do not change `pyron/`. Record it
as a finding in `../progress-tracker.md`, let the §7 decision rules in
`plan.md` route it, and propose it for Phase 3. If something out of scope
turns out to be needed to finish an increment, stop, record it under
"Blocked / unresolved" in the tracker, and propose a scoped follow-up rather
than expanding this phase.
