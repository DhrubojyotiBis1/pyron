# AGENTS.md

This repository uses a persistent context system under `context/` so that
any coding agent — Claude Code or otherwise — can pick up work with an
accurate understanding of the project, without re-deriving context from
scratch or trusting stale assumptions.

**Read this file first, every session, before touching code or docs.**

## What this project is (one paragraph)

An experimental Go-inspired M:N concurrency/runtime abstraction for
free-threaded Python — many logical tasks scheduled onto a smaller pool of
real threads. **Phase 1 (minimal scheduler: one global queue, N workers) is
implemented and validated**; Phase 2 (measure, then decide: benchmark
harness, baselines, and an ADR on blocking tasks — no runtime changes) is
planned in `context/phase-2/` but not started. Exact current
state: `context/progress-tracker.md`. Full detail:
`context/project-overview.md`.

## The context files and when to read them

| File | Read it when you need to... |
|---|---|
| `context/project-overview.md` | Understand *why* this project exists, its scope, and non-goals. Read once per session for orientation, or when a request seems to fall outside project scope. |
| `context/architecture-context.md` | Understand current architectural thinking, proposed components, and open questions before designing or changing anything structural. **Never treat this as proof something is implemented.** |
| `context/progress-tracker.md` | Determine what **actually** exists right now. Read this before claiming any feature is done, and update it after every change. |
| `context/ai-workflow-rules.md` | Understand the process you're expected to follow: scoping, validation, performance-claim rules, and documentation-update obligations. Read fully before your first change in a session. |
| `context/coding-standards.md` | Understand engineering/design rules — especially concurrency safety, ownership, and testing/benchmarking expectations — before writing implementation code. |

## How to determine the actual current state

Do **not** rely on `architecture-context.md` alone to decide what exists.
Use this order:

1. The actual code in the repository, and whether its tests pass.
2. `context/progress-tracker.md` (must match #1 — if it's out of sync,
   fix the tracker before doing anything else).
3. `context/architecture-context.md` for *intent*, clearly separated from
   *implementation* by its status tags (`CONFIRMED` / `DECIDED` /
   `PROPOSED` / `EXPERIMENTAL` / `OPEN QUESTION` / `REJECTED`).

An architectural design being written down is never evidence that it
exists in code.

## How implementation work should proceed

Full detail in `context/ai-workflow-rules.md`. Summary:

1. Establish current state (see above) before changing anything.
2. Scope your task to the current phase in `progress-tracker.md`; flag,
   don't silently absorb, any request that implies a larger scope.
3. State your plan before implementing anything non-trivial.
4. Implement incrementally, in testable steps.
5. Validate (tests + concurrency-safety reasoning) before calling anything
   done.
6. Any performance claim requires a committed, reproducible benchmark with
   recorded environment details — no exceptions.
7. Update the relevant context file(s) (see table in
   `ai-workflow-rules.md` §9) as part of the same change, not as an
   afterthought.

## How to validate work before declaring it complete

See `context/ai-workflow-rules.md` §7 and §10 for the full checklist.
At minimum: tests pass, concurrency safety was actually reasoned about
(not assumed), and `progress-tracker.md` reflects reality.

## When context files must be updated

See the table in `context/ai-workflow-rules.md` §9. In short: code changes
always update `progress-tracker.md`; changes to a `CONFIRMED` architectural
decision require an ADR entry in `architecture-context.md`; changes to
project scope/direction require updating `project-overview.md` (rare).

## Handling conflicts between documentation and implementation

Code + passing tests win for "what exists." If `progress-tracker.md`
disagrees with the code, fix the tracker first, then proceed. If
`architecture-context.md` describes something CONFIRMED that the code
contradicts, treat that as a bug to flag explicitly, not something to
silently "fix" by rewriting the architecture doc to match — raise it, then
resolve it deliberately (new ADR entry either way, explaining what changed
and why).

## Claude Code note

`CLAUDE.md` at the repo root imports this file. Claude Code should treat
this document as the operative instructions; `CLAUDE.md` exists only for
tool compatibility, not as a second source of truth.
