# Project Overview

> **Status: Phase 1 — minimal M:N scheduler implemented (S0–S6); Phase 0 (initialization) is complete.**
> Last updated: 2026-09-26 (see `progress-tracker.md` for what exists)

## 1. What this project is

An experimental exploration of a **Go-inspired M:N concurrency/runtime abstraction
for free-threaded Python** (PEP 703 / no-GIL CPython builds).

The core idea:

```text
M logical tasks
      ↓
Runtime / Scheduler
      ↓
N real Python threads
      ↓
Multiple CPU cores
```

Many logical "tasks" (M) are multiplexed onto a smaller, bounded set of real OS
threads (N) by a userspace scheduler, so that CPU-bound Python code can run
across multiple cores without the caller manually managing threads, thread
pools, or executors.

## 2. Why this project exists

Free-threaded Python removes the GIL as a hard barrier to CPU-bound
parallelism, but the standard library does not yet offer a first-class,
ergonomic *scheduling* abstraction comparable to Go's goroutines + scheduler.
This project exists to explore whether a similar M:N model is viable,
useful, and worth building in Python — not to assert that it already is.

## 3. The problem being explored

- Can a userspace scheduler multiplex many logical tasks onto a bounded pool
  of real threads under free-threaded Python, correctly and safely?
- What primitives does this require (task representation, run queues,
  work distribution/stealing, synchronization, lifecycle management)?
- Does this provide a measurable, real benefit over existing options
  (`threading`, `concurrent.futures`, `asyncio`, `multiprocessing`) on
  free-threaded builds — and under what workloads, if any?

This project is a **research vehicle**. The answer to "does this work well"
is not assumed; it is the thing being investigated.

## 4. Long-term vision (aspirational — not current scope)

- A library-level runtime where users spawn lightweight logical tasks and
  the runtime schedules them across N worker threads pinned to available
  cores.
- Scheduling strategies (e.g. work-stealing, work-sharing) evaluated
  empirically against each other.
- Possibly ergonomic APIs/decorators for structured concurrency.

Nothing in this section is a commitment. It is a direction, not a plan.

## 5. Current goals (Phase 0)

- Establish a durable, honest project context system (this document set).
- No scheduler, runtime, or benchmark code is written in this phase.

Future phases and their goals are tracked in `progress-tracker.md`, not here.
This file describes *why the project exists*, not *what's done*.

## 6. Expected user experience (hypothesis — unvalidated)

A rough, non-binding sketch of what a future API *might* look like:

```python
handle = runtime.spawn(fn, *args)
result = handle.result()
```

The exact API, naming, and ergonomics are undecided and will be shaped by
what the scheduling experiments actually require. Do not treat this sketch
as a spec.

## 7. Boundaries — explicitly out of scope

- Modifying CPython internals or the interpreter itself.
- Reimplementing or replacing the Python runtime.
- Distributed / multi-process / multi-machine scheduling.
- `asyncio` integration (initially — may be revisited later as a distinct
  question, not assumed).
- Any claim of universally outperforming Go, or any other language/runtime.
- Production readiness of any kind, at this stage.

## 8. How success should be evaluated

Success is evaluated **per experiment**, against reproducible evidence in
`progress-tracker.md` — never as a single global claim. Candidate criteria
(to be refined as real work begins):

- A scheduler that correctly executes M logical tasks across N threads,
  verified by tests (no data races, no deadlocks, no lost/duplicated work).
- Reproducible benchmarks comparing CPU-bound throughput/latency under this
  runtime vs. `concurrent.futures.ThreadPoolExecutor` on a free-threaded
  build, and vs. `multiprocessing`, with hardware/build/config recorded.
- Findings — positive *or* negative — documented as evidence, not asserted
  as belief.

Success is explicitly **not**: "faster than Go," "replaces asyncio," or any
performance claim not backed by a reproducible benchmark artifact.

## 9. Confirmed vs. hypothesis vs. future vs. non-goal

| Statement | Category |
|---|---|
| Explore an M:N scheduler for free-threaded Python | Confirmed goal |
| Stay Python-first; no CPython modification | Confirmed constraint |
| A work-stealing scheduler will outperform a simple queue | Hypothesis |
| The runtime will offer ergonomic decorators/structured concurrency | Future possibility |
| This project modifies CPython | Non-goal |
| This project replaces asyncio | Non-goal |
| This project will beat Go's runtime in general | Non-goal |

## 10. Where to look next

- Architectural thinking and open questions → `architecture-context.md`
- Actual current state / what exists today → `progress-tracker.md`
- How agents should work in this repo → `ai-workflow-rules.md`
- Engineering/design rules → `coding-standards.md`
