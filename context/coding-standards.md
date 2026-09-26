# Coding & Design Standards

These standards exist primarily to keep a **concurrent runtime**
understandable as it grows — not merely to enforce formatting. Formatting is
the least important thing here.

## 1. Guiding principle

As components multiply, it must always be possible to answer, for any piece
of state: **who owns it, who is allowed to mutate it, and under what
synchronization.** If that question doesn't have a clear answer, the design
is not ready to be merged, regardless of whether it "works."

## 2. Python implementation

- Target free-threaded CPython builds (PEP 703) as the primary environment;
  note explicitly if code also happens to work under a GIL build, but do
  not design around the GIL as a safety net.
- Use type hints on all public functions/classes/methods.
- Prefer explicit, boring code over clever metaprogramming — this is a
  systems project where correctness and readability of concurrency logic
  matters more than API sugar.
- Docstrings on every public component describing: purpose, ownership of
  any state it holds, and thread-safety guarantees (or lack thereof).

## 3. Component design & ownership

- Every component (scheduler, worker, queue, task object, etc.) must
  document, at the top of its module or class:
  - What state it owns.
  - Which thread(s) are allowed to touch that state, and how.
  - What it explicitly does *not* guarantee.
- Prefer single-owner state (one thread/component responsible for mutating
  a piece of data) over shared-write state. If shared-write state is
  unavoidable, it must be called out explicitly (see §4).

## 4. Concurrency safety & shared mutable state

- Shared mutable state is a deliberate design decision, not a default.
  Any shared mutable state must have, next to its definition, a one-line
  comment naming the synchronization mechanism protecting it (lock,
  queue, atomic op, etc.) and what invariant it protects.
- Prefer message-passing (queues) between threads over shared state
  protected by locks, where reasonably possible — it's easier to reason
  about for this kind of scheduler.
- If a lock is used, document what it protects and the maximum expected
  hold time. Long-held locks in scheduling hot paths are a design smell —
  flag them, don't just silence a lint.
- No busy-waiting/spin loops without an explicit justification comment
  (e.g. "spinning here because X, expected wait < Yµs") — otherwise use
  blocking primitives.

## 5. Task & worker abstractions

- A "task" (logical unit of work) and a "worker" (real OS thread executing
  tasks) are distinct concepts and must not be conflated in naming or
  implementation, even in early prototypes.
- Task objects should be immutable or single-owner once submitted, except
  for well-defined state transitions (e.g. pending → running → done)
  that go through a controlled, documented path.
- Worker lifecycle must be explicit: how a worker starts, how it is told to
  stop, and how in-flight tasks are handled on shutdown — "undefined" is
  not an acceptable answer once a worker abstraction exists.

## 6. Lifecycle management

- Every long-lived component (runtime, scheduler, worker pool) must have
  an explicit start/stop (or equivalent context-manager) API. No
  component should rely on implicit cleanup via garbage collection for
  correctness.
- Shutdown behavior (drain vs. cancel in-flight work) must be documented
  and tested, not left implicit.

## 7. Queues & scheduling abstractions

- Queue implementations used for task distribution must document their
  ordering guarantees (FIFO? none? priority?) and their behavior under
  contention.
- Any scheduling policy (e.g. work-stealing) must be implemented behind an
  interface that allows swapping strategies for experimentation — this
  project exists to compare approaches, not commit to one prematurely.

## 8. Error handling

- Exceptions raised inside a logical task must never be silently swallowed
  by a worker thread. They must be captured and surfaced to whatever holds
  the task's handle/future.
- An unhandled exception in scheduler/worker infrastructure code (as
  opposed to user task code) should fail loudly, not degrade silently —
  silent degradation in a scheduler is worse than a crash during this
  experimental phase.
- Never use bare `except:`; catch specific exceptions or re-raise.

## 9. Testing

- Correctness tests for concurrent components must include:
  - Deterministic single-threaded-equivalent tests where possible (test
    the logic, not just the concurrency).
  - Stress/soak tests that run with many tasks/threads repeatedly to
    surface races (a test that "usually passes" is not passing).
- When a race or deadlock is found and fixed, add a regression test that
  would have caught it.
- Prefer `pytest` unless a strong reason emerges otherwise; keep test
  dependencies minimal.

## 10. Benchmarking

- Benchmarks live separately from correctness tests and are never run as
  part of normal test suite runs (they're slow and noisy by nature).
- Every benchmark script must record: CPython version/build, whether
  free-threading is enabled, OS, CPU core count, and date run.
- Report multiple runs (not a single sample); note variance, not just a
  mean.
- A benchmark script must be committed alongside any number quoted in
  documentation — see `ai-workflow-rules.md` §8.

## 11. Performance claims in code comments/docs

- Do not write comments like "this is fast because X" without a benchmark
  reference. Prefer "this is expected to be faster because X — see
  `progress-tracker.md` experiment #N" once such an experiment exists.

## 12. What this document intentionally does not mandate

- A specific formatter/linter, dependency manager, or package layout —
  pick pragmatically when the project reaches a point of needing one, and
  record the choice in `progress-tracker.md`.
- Any specific scheduling algorithm — that's an architectural question,
  tracked in `architecture-context.md`, not a coding standard.
