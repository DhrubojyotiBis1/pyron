# Phase 1 — Verification

> Status: PLANNED. Design-time checks below were performed against the
> written design on 2026-09-26 and re-checked after the sign-off answers
> (required `n_workers`, cancellation seams); **code-level checks are all
> pending** since no code exists. Last updated: 2026-09-26.

Two kinds of verification are separated here so neither is mistaken for the
other: (A) checks that the *design* is sound (done on paper), and (B) checks
that the *implementation* is correct (to be done with tests and stress runs).

## 1. State model check (design-time)

| Check | Result |
|---|---|
| Every non-terminal state has at least one exit | Pass: `PENDING`→{`RUNNING`,`CANCELLED`}; `RUNNING`→{`COMPLETED`,`FAILED`} |
| Every state is reachable from `PENDING` | Pass |
| Terminal states have no exits | Pass by definition (`COMPLETED`, `FAILED`, `CANCELLED`) |
| Exactly one terminal state per task | Pass, given claim/cancel atomicity under the task lock |
| Claim and cancel cannot both succeed | Pass, same lock; loser observes and no-ops |
| Waiters never hang on a crashing task | Pass: `BaseException` path marks `FAILED` before re-raise |
| Tasks stranded by dead workers are resolved | Pass: final sweep at shutdown cancels leftovers |
| Distinct outcomes needed by the handle (value / error / cancelled) | Pass: three separate terminal states |
| Consistent with the existing example `pending → running → done` in `coding-standards.md` §5 | Pass: "done" is split into three outcomes; no contradiction |
| No dead or unreachable state | Pass; `WAITING` deliberately omitted because nothing could transition into it (ADR-001) |

Open point: a race exists on paper between `next_task` returning a task and
`run` claiming it while shutdown-cancel drains. It is benign (a task already
fetched by a worker is claimed by that worker; drained tasks are not in the
queue any more), but it **must** be covered by a test (§5, S6).

## 2. Entity relations and extensibility check (design-time)

| Future change | What changes | What must not change | Result |
|---|---|---|---|
| Work-stealing / per-worker queues | New class implementing `Scheduler` | `Worker`, `Runtime`, `Task`, `TaskHandle` | Pass: the seam is the scheduler, not a queue |
| Different queue behavior (priority, bounded) | Inside a scheduler implementation | Everything else | Pass |
| New task kind (e.g. suspendable) | Overriding the invocation hook | State-handling code | Partial: state handling reused; suspension additionally needs a new state and a resubmit path on `Scheduler`, which changes the Worker/Scheduler contract. Recorded as a known consequence in ADR-001. |
| Cancelling running tasks | The transition table and `Task.cancel` only; optionally a token via the invocation hook | `Worker`, `Scheduler`, `Runtime` (except shutdown policy), `TaskHandle` interface | Pass, given the seams in `implementation.md` §3.7 are actually built; a new ADR is required. Implementation-time check: grep confirms the "pending only" rule appears nowhere except the transition table and `Task.cancel`. |
| Different worker type (e.g. pinned) | New class with the same source dependency | Scheduler, Task | Pass |
| Dynamic worker count | `Runtime` only | Scheduler contract (already supports N callers) | Pass |

Relationship rules confirmed: Task and Worker share no inheritance; all
cross-entity links are composition or protocol dependency.

## 3. SOLID check (design-time)

| Principle | How the design satisfies it | Residual concern |
|---|---|---|
| Single responsibility | Task: state machine; Handle: caller view; Scheduler: distribution; Worker: execution loop; Runtime: lifecycle and wiring | `Runtime` combines wiring and lifecycle; acceptable while it is a thin facade — revisit if it grows |
| Open/closed | New policies and task kinds are added by implementing a protocol or overriding one hook | The Task hook is only sufficient for non-suspending variants |
| Liskov substitution | Shared scheduler contract tests are parametrized over every implementation, so substitutability is tested, not assumed | Contract must be kept complete as implementations are added |
| Interface segregation | `Worker` sees only `next_task`; `Runtime` sees `submit`/`close`/`drain`; `Handle` sees only the public task surface | none |
| Dependency inversion | `Runtime` and `Worker` depend on protocols; the scheduler is injected | none |

## 4. Architecture and rules compliance (design-time)

| Rule | Source | Result |
|---|---|---|
| Components match proposed set (Task, Scheduler, Worker, run queue, handle) | `architecture-context.md` §2 | Pass; `Runtime` facade added (recorded as `PROPOSED`) |
| Execution flow matches | `architecture-context.md` §3 | Pass; shutdown policy now proposed (ADR-003) |
| No CPython modification; pure Python; free-threaded target | §4 | Pass |
| No distributed scheduling | §4 | Pass |
| Task and worker distinct | `coding-standards.md` §5 | Pass |
| Single-owner or documented shared state | §3, §4 | Pass; ownership table in `implementation.md` §4 |
| Prefer message passing to locks | §4 | Deviation, justified: two O(1) locks, no user code beneath (ADR-003) |
| No spin loops | §4 | Pass; all waits are blocking primitives |
| Explicit lifecycle; documented, tested shutdown | §6 | Pass in design; test required |
| Swappable scheduling policy | §7 | Pass |
| Queue ordering documented | §7 | Pass: FIFO, unbounded |
| Task exceptions never swallowed; infra fails loudly; no bare `except` | §8 | Pass |
| No performance claims | `ai-workflow-rules.md` §8 | Pass; none made |
| Scope limited to current phase; blocked-task limitation recorded | `ai-workflow-rules.md` §2 | Pass; `scope.md` §3 |
| No CONFIRMED decision altered | `ai-workflow-rules.md` §6 | Pass; nothing is `CONFIRMED` yet |
| No `CONFIRMED` claim without code + tests | `AGENTS.md` | Pass; all new ADRs are `PROPOSED` |

No violation of an architectural rule was found. One justified deviation
(locks vs. message passing) and one incomplete extensibility point
(suspension) are recorded rather than hidden.

## 5. Test plan (implementation-time — pending)

Framework: pytest, minimal dependencies (`coding-standards.md` §9). Hangs
must fail rather than block: use bounded joins/waits with timeouts.

| Area | Tests |
|---|---|
| State machine (S1) | All four legal transitions succeed; every other transition attempt fails; terminal states immutable; outcome visible only after terminal; `BaseException` path marks `FAILED` and re-raises |
| Claim vs cancel race (S1/S6) | Many tasks, many threads: for each task, exactly one of {ran, cancelled}; never both; never neither |
| Handle (S2) | Value, exception and cancelled outcomes; timeout; cancel on pending / running / finished |
| Cancellation seams (S1/S2) | Tests assert against the transition table and the returned value of `cancel`, not hard-coded "running can't be cancelled" expectations, so a policy change fails in one obvious place; shutdown-cancel and handle-cancel both go through `Task.cancel` |
| Runtime construction (S5) | `n_workers` required (omitting it fails); rejects zero, negative, non-integer; exactly `n_workers` worker threads started |
| Scheduler contract (S3) | Parametrized so future schedulers reuse it: FIFO for this implementation; submit after close rejected; next_task returns "no task" only when closed and empty; close wakes all blocked callers; drain is atomic; no task delivered twice under contention |
| Close vs submit race (S3/S6) | Concurrent submitters racing `close`: every submit either raises or its task is later delivered/drained; none stranded |
| Worker (S4) | Exits cleanly on close; crash recorded and surfaced; other workers unaffected |
| Runtime integration (S5) | M ≫ N tasks: each runs exactly once, none lost or duplicated; exceptions surface via handles; both shutdown modes; shutdown idempotent; spawn before start / after shutdown; context manager |
| Fetch vs shutdown-cancel race (S6) | Shutdown-cancel while workers are fetching: every task ends in exactly one terminal state |
| Stress / soak (S6) | Repeated many-task runs with many threads, run on a free-threaded build with the GIL disabled; no failures across repeats |
| Documented limitation (S6) | A pool of N workers whose tasks block on queued tasks' results hangs; asserted via timeout to record the behavior |
| Concurrency-safety evidence (S6) | Written note in the tracker describing what races were probed and how (per `ai-workflow-rules.md` §7) |

Every race or deadlock found and fixed gets a regression test.

## 6. Completion checklist (all currently unchecked)

Mirrors `ai-workflow-rules.md` §10.

- [ ] Change is scoped to Phase 1 (or scope expansion was flagged)
- [ ] Tests exist and pass for all new behavior
- [ ] Stress runs pass repeatedly on a free-threaded build with GIL disabled
- [ ] Concurrency safety was checked, not assumed (§5 evidence recorded)
- [ ] Ownership/synchronization documented in every component
- [ ] No performance claim anywhere
- [ ] `progress-tracker.md` reflects the real state (no aspirational entries)
- [ ] ADR-001..003 promoted to `CONFIRMED` with evidence, or revised
- [ ] Known limitations (`scope.md` §3) still accurate, or updated
- [ ] No document contradicts another
