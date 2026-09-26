# AI Agent Workflow Rules

> These rules exist to prevent architectural drift, false progress claims,
> and unmeasured performance claims in an experimental concurrency runtime.
> They apply to **every** coding agent working in this repository, not just
> the one that wrote them.

## 0. Ground truth hierarchy

When determining "what actually exists" in this project, trust sources in
this order:

1. **Actual code + passing tests** in the repository.
2. **`progress-tracker.md`** (must reflect #1 — if it doesn't, fix the
   tracker before doing anything else).
3. **`architecture-context.md`** — describes intent and proposals, which
   may or may not be implemented yet. Never treat an entry here as evidence
   that code exists.
4. **`project-overview.md`** — vision and goals, the least authoritative
   about current state.

**A design being described in `architecture-context.md` is never evidence
that it is implemented.** Only code + tests are evidence of implementation.

## 1. Before changing anything

- Read `AGENTS.md`, then `progress-tracker.md`, then skim
  `architecture-context.md` for relevant sections.
- Run the existing test suite (once one exists) to establish a known-good
  baseline before making changes.
- If the requested task references architecture that is marked PROPOSED or
  EXPERIMENTAL (see `architecture-context.md` status legend), treat it as
  *not yet real* — implementing it is the task, not a formality.

## 2. Task scoping

- Work only within the **current phase** as recorded in
  `progress-tracker.md`. If a request implies work outside the current
  phase (e.g. asking for work-stealing before a basic scheduler exists and
  is validated), say so explicitly and propose scoping it as a new
  phase/experiment rather than silently expanding scope.
- Prefer the smallest change that produces a testable, observable result.
- Do not implement speculative features "while you're in there." If you
  notice something worth doing later, record it as an open question or
  planned item in `progress-tracker.md` instead of doing it now.

## 3. Planning

- For anything larger than a small fix: state in your own response (a) what
  you understand the current state to be, (b) what you intend to change,
  and (c) how you will validate it, before writing code.
- If the plan requires an architectural decision not yet made, stop and
  either ask, or add an entry to the Architecture Decision Log in
  `architecture-context.md` marked PROPOSED and flag it for review rather
  than deciding unilaterally on anything with wide blast radius (e.g. task
  representation, scheduler interface, synchronization strategy).

## 4. Incremental implementation

- Build in small, independently testable increments. A change that can't
  be validated on its own is too large.
- Never implement multiple unvalidated architectural ideas in the same
  change. Land and validate one thing before building on it.

## 5. Experimentation

- This is a research project — many changes are experiments, not final
  designs. Label experimental code/branches clearly (e.g. module docstring
  or `EXPERIMENTAL:` marker) and record the experiment in
  `progress-tracker.md`'s Experiments section, win or lose.
- Failed or inconclusive experiments must be recorded, not deleted and
  forgotten. Negative results are valuable data for this project.

## 6. Architecture changes

- Do not silently change an architectural decision that's marked CONFIRMED
  in `architecture-context.md`. Changing it requires:
  1. A new dated entry in the Architecture Decision Log explaining what
     changed and why (evidence, not preference).
  2. Updating the status of the old decision (e.g. to REJECTED, with the
     reason) rather than deleting it.
- Proposing a *new* idea (status PROPOSED) does not require this ceremony —
  only changing something already CONFIRMED does.

## 7. Validation before "done"

A change is not complete until:

- Relevant tests pass (correctness first — concurrency bugs are often
  silent; add regression tests for any race/deadlock found and fixed).
- For anything touching shared state, threads, or scheduling: describe how
  you checked for races/deadlocks (tests, stress runs, tooling), not just
  "it ran once without error."
- `progress-tracker.md` is updated to reflect the real new state.

## 8. Performance claims

- **No performance claim, comparison, or number may appear in any
  documentation without a reproducible benchmark** committed alongside it
  (script + how to run it + recorded environment: CPython build,
  free-threaded on/off, OS, CPU, core count, date).
- "Should be faster because X" is a hypothesis, not a claim — phrase it as
  one, and put it in Open Questions, not in a results section.
- Benchmark numbers are point-in-time and environment-specific. Re-running
  benchmarks after a change is expected before restating a claim.

## 9. Documentation updates — what triggers what

| You changed... | You must update... |
|---|---|
| Any implementation code | `progress-tracker.md` |
| A CONFIRMED architectural decision | `architecture-context.md` (ADR log) |
| Scope/direction of the project itself | `project-overview.md` (rare) |
| Coding/testing/benchmarking conventions | `coding-standards.md` |
| This workflow itself | `ai-workflow-rules.md`, note it in the tracker |

Small code changes (e.g. a bug fix within existing scope) do **not** require
touching `architecture-context.md` or `project-overview.md` — avoid
bureaucratic overhead for changes that don't change intent or state.

## 10. Completion criteria checklist

Before declaring a task complete, confirm:

- [ ] Change is scoped to the current phase (or scope expansion was flagged)
- [ ] Tests exist and pass for the new behavior
- [ ] Concurrency safety was actually checked, not assumed
- [ ] Any performance claim has a committed, reproducible benchmark
- [ ] `progress-tracker.md` reflects the real state (no aspirational entries)
- [ ] Architecture doc updated if a CONFIRMED decision changed
- [ ] No documentation now contradicts another document

## 11. Explicitly forbidden patterns

- Marking something "done" or "implemented" in `progress-tracker.md` when
  it only exists as a design in `architecture-context.md`.
- Adding benchmark numbers without a committed script that reproduces them.
- Silently reworking a CONFIRMED architectural decision.
- Expanding scope into a future phase without flagging it.
- Deleting a failed experiment's record instead of logging it.
