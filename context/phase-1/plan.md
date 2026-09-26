# Phase 1 — Plan: Minimal M:N Scheduler (1 global queue, N workers)

> **Status: PLANNED — not started. No code exists.**
> Last updated: 2026-09-26
> The five sign-off decisions in §6 were answered on 2026-09-26 and the
> related ADRs are `DECIDED` (direction only). Nothing is `CONFIRMED` until
> the implementation is validated (`../architecture-context.md` §8).

Companion documents in this folder:

| File | Contents |
|---|---|
| `plan.md` (this file) | Goal, approach, increments, exit criteria, pending decisions |
| `scope.md` | What is in / out of scope, and the known limitations of this phase |
| `implementation.md` | Entities, task states, low-level design, ownership and synchronization |
| `verification.md` | How the design and the eventual code are checked (states, SOLID, architecture rules, tests) |

## 1. Goal

Prove the basic execution flow from `architecture-context.md` §3 works
correctly and safely on a free-threaded CPython build:

```text
M logical tasks  →  1 global FIFO queue  →  N worker threads
```

"Correctly" means: every submitted task reaches exactly one terminal state,
runs at most once, has its result or exception delivered to its handle, and
shutdown is explicit and deterministic. It does **not** mean "fast" — see
`scope.md` for why no performance claims are made.

## 2. Approach (one paragraph)

Build a small library in seven entities (`Task`, `TaskState`, `TaskHandle`,
`Scheduler` protocol, `GlobalQueueScheduler`, `Worker`, `Runtime`). The
swappable seam is the **Scheduler**, not the queue, so a later work-stealing
scheduler can replace the global queue without touching `Worker` or
`Runtime`. Each task is a guarded state machine; each worker is a plain
loop; all cross-thread coordination goes through two short-held locks
(per-task, per-scheduler), both documented. Details: `implementation.md`.

## 3. Increments

Each increment must be independently testable and validated before the next
begins (`ai-workflow-rules.md` §4).

| # | Increment | Validated by |
|---|---|---|
| S0 | Environment and scaffolding: confirm a free-threaded interpreter is available (GIL reported disabled), set up pytest, create package layout | Trivial test runs under the free-threaded build; GIL-state assertion |
| S1 | Errors, `TaskState`, `Task` (state machine + outcome slot) | Transition-table tests, terminal-state immutability, cancel-vs-claim race test |
| S2 | `TaskHandle` | Behavior per state, timeouts, exception propagation, cancel |
| S3 | `Scheduler` protocol + `GlobalQueueScheduler` | Shared scheduler contract tests, close/submit atomicity test |
| S4 | `Worker` | Clean exit on close; crashing-task behavior; crash recording |
| S5 | `Runtime` (lifecycle, spawn, shutdown) | Integration test: M ≫ N tasks each run exactly once; both shutdown modes |
| S6 | Stress and race hardening; documentation promotion | Repeated stress runs on free-threaded build; tracker + ADR update |

## 4. Exit criteria

Phase 1 is complete only when all of the following hold (mirrors
`ai-workflow-rules.md` §10):

- All tests pass repeatedly (not once) on a free-threaded build with the GIL
  disabled, including the stress suite.
- The verification checklist in `verification.md` §6 is fully checked.
- Every component documents state ownership, permitted threads and
  guarantees / non-guarantees.
- `progress-tracker.md` reflects the real state, with the experiment(s)
  recorded, including any negative or inconclusive result.
- ADR-001..003 are either promoted to `CONFIRMED` (with evidence) or
  superseded/`REJECTED` with reasoning.
- No performance number appears in any document.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Subtle races in the claim/cancel path or close/submit path | Locks with documented invariants; dedicated race tests; repeated stress runs |
| Tests that "usually pass" hide races | Stress loops with many tasks/threads; join timeouts so a hang fails rather than blocks |
| Design over-fits the global queue and blocks later work-stealing | Scheduler protocol as the seam; scheduler contract tests reused for future implementations |
| Blocking tasks deadlock the pool | Documented as a known limitation (`scope.md` §3); one test demonstrates it with a timeout; not solved in this phase |
| Free-threaded build unavailable locally | S0 verifies first; if unavailable, stop and raise before any further work |

## 6. Sign-off decisions (answered 2026-09-26)

| # | Decision | Answer | Recorded in |
|---|---|---|---|
| 1 | Task states | Five states (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`) accepted "for now" | ADR-001 |
| 2 | Cancellation | Pending-only in Phase 1. The design must keep it possible to change later, so cancellation policy is isolated behind explicit seams (`implementation.md` §3.7) | ADR-001 |
| 3 | Swappable seam | `Scheduler`, not a queue, "as of now" | ADR-002 |
| 4 | `BaseException` in a task | Mark the task `FAILED`, then re-raise so the worker crashes loudly; start there | ADR-001 |
| 5 | Worker count | `n_workers` is a **required explicit parameter**; no CPU-derived default | ADR-003 |

"For now" and "as of now" mean these may be revisited through a new ADR
entry when evidence warrants; they are not permanent commitments.

Still `PROPOSED` (not part of the sign-off above): the synchronization and
shutdown details in ADR-003 — the lock structure, the two shutdown modes
and the final sweep. They are implementation-level and will be validated by
tests before promotion.

## 7. What comes after Phase 1 (not committed)

Candidates, to be scoped as their own phases/experiments only after Phase 1
is validated: benchmarking harness; work-stealing scheduler behind the same
protocol; suspension and a waiting/suspended state; backpressure. Tracked in
`../progress-tracker.md` only once actually queued.
