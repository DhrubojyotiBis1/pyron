# Phase 2 — Plan: Measure, then decide

> **Status: IN PROGRESS — P2.1 complete (accepted by the owner on 2026-10-04 at 37/40 rows; see Experiments 2 and 4); P2.2 next, pending decision 4. Primary benchmark environment for P2.2–P2.4: the Claude Code cloud container (§6 decision 3, amended 2026-10-04). See `../progress-tracker.md` for what exists.**
> Last updated: 2026-10-04
> Sign-off decisions 1–3 in §6 were answered on 2026-10-04; decision 4 (the
> Phase 3 decision rules) is pending and must be answered before any P2.2–P2.4
> result is looked at.

Companion documents in this folder:

| File | Contents |
|---|---|
| `plan.md` (this file) | Goal, approach, increments, exit criteria, risks, sign-off decisions, decision rules for Phase 3 |
| `scope.md` | What is in / out of scope, and the known limitations of this phase |
| `implementation.md` | Benchmark harness design, the design of each experiment, the structure of ADR-004 |
| `verification.md` | How the plan and the eventual measurements are checked (design-time and execution-time) |

## 1. Goal

Produce the evidence needed to choose what Phase 3 builds, instead of
choosing it by preference. Phase 2 answers two questions:

1. **Is the single global queue actually a bottleneck, and where does the
   per-task cost go?** This decides whether per-worker queues and work
   stealing are worth building. The single-lock contention is recorded in
   `../phase-1/scope.md` §3 limitation 5 as a hypothesis, never measured.
2. **How should Pyron handle tasks that block?** This decides whether and how
   the documented deadlock (`../phase-1/scope.md` §3 limitations 1–2) is
   addressed, and what that does to ADR-001 and ADR-002.

Phase 2 adds **no runtime features** and changes nothing in `pyron/`. Its
outputs are a shared benchmark harness, recorded experiments, one ADR
(`PROPOSED`, then `DECIDED` on sign-off), and a recorded choice of Phase 3
track.

## 2. Approach (one paragraph)

First turn the reusable parts of `benchmarks/cpu_saturation.py` into a shared
harness and prove the refactor did not change what it measures (P2.1). Then
run three measurement increments on that harness: the scheduler alone under
contention, including a best case for sharded queues (P2.2); end-to-end
`Runtime` against `ThreadPoolExecutor` and raw threads across task sizes
(P2.3); and a breakdown of the per-task cost into its parts (P2.4). In
parallel, write ADR-004 comparing ways to handle blocking tasks, backed only
by small throwaway spikes where a fact must be checked (P2.5). Finally apply
decision rules that were fixed before the data was seen (§7) and record the
Phase 3 choice (P2.6). Details: `implementation.md`.

## 3. Increments

Each increment must be independently validated before anything that depends
on it begins (`ai-workflow-rules.md` §4). P2.5 depends on nothing else and
may run alongside P2.2–P2.4. P2.6 depends on all of them.

| # | Increment | Validated by |
|---|---|---|
| P2.1 | Shared benchmark harness; `cpu_saturation.py` ported onto it | Unit tests for the harness's pure helpers; `--quick` smoke run of every script; a reproduction run of Experiment 1's configuration whose medians fall within the recorded spread (`verification.md` §5) |
| P2.2 | Scheduler contention baseline: `GlobalQueueScheduler` alone vs a bare locked deque, `queue.SimpleQueue`, and a throwaway sharded-queue upper bound; saturated and streaming modes; hand-off latency | Experiment recorded in the tracker; every item delivered exactly once in every run; spread reported |
| P2.3 | End-to-end baseline: `Runtime` vs `ThreadPoolExecutor` vs raw threads across task sizes (including sub-0.1 ms) and producer counts | Experiment recorded; every task result verified; spread reported; granularity open question annotated |
| P2.4 | Per-task cost breakdown: each step of a task's life timed in isolation, reconciled against the P2.3 end-to-end figure; wake-up cost separated from lock cost | Experiment recorded with a cost table and the unexplained remainder stated |
| P2.5 | ADR-004: handling blocking tasks (comparison and recommendation; spikes only for factual questions) | ADR written as `PROPOSED` with every option scored against the same criteria; spikes recorded as experiments; owner sign-off moves it to `DECIDED` |
| P2.6 | Decision gate and documentation | Rules in §7 applied as written; Phase 3 choice and its evidence recorded in the tracker; `architecture-context.md` §5 annotated; `verification.md` §6 checklist complete |

## 4. Exit criteria

Phase 2 is complete only when all of the following hold:

- The shared harness is committed, `cpu_saturation.py` runs on it, and the
  reproduction run is recorded.
- P2.2, P2.3 and P2.4 are each recorded in `../progress-tracker.md` as an
  experiment in the standard format, with the committed script, the exact
  command, and the environment. Inconclusive results are recorded as
  inconclusive.
- ADR-004 is `DECIDED` (owner sign-off), or explicitly deferred with a
  recorded reason.
- The Phase 3 track is chosen by the §7 rules, and the tracker records which
  rule fired and on what evidence.
- Nothing in `pyron/` changed; the full test suite still passes (160 tests at
  the start of the phase).
- Every number in any document traces to a committed script and a recorded
  environment (`ai-workflow-rules.md` §8).
- The verification checklist in `verification.md` §6 is fully checked.

Results from the owner's separate runs on other machines (§6 decision 3) are
welcome evidence but are **not** an exit criterion.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Run-to-run noise hides real differences (Experiment 1 saw up to 19% spread at 8+ threads on the M2; the cloud container's tenancy is unknown, so other tenants may add noise) | More repetitions; report spread beside every median; treat differences inside the spread as "no difference"; alternate variants within a session; M2 runs as a secondary cross-check |
| Heterogeneous cores (4P+4E) distort scaling and load-balance results | Record core types; report the 1–4 thread range separately from 8+; never attribute an effect to Pyron when raw threads show it too |
| Isolated micro-measurements don't add up to the end-to-end cost | P2.4 reports the reconciliation and the unexplained remainder explicitly instead of forcing a match |
| Reading the data to fit a preferred Phase 3 | Decision rules fixed and signed off before results are seen (§7, §6 decision 4) |
| The refactor in P2.1 silently changes what `cpu_saturation.py` measures | Reproduction run against Experiment 1 before any new benchmark is trusted |
| Measurement turns into open-ended digging | Each increment ends with a recorded result, inconclusive allowed; follow-ups are written down, not pursued inside the increment |
| A spike in P2.5 grows into a feature | Spikes live outside `pyron/`, answer one stated question each, and are labelled `EXPERIMENTAL` |
| A third-party extension silently re-enables the GIL when imported (relevant to the greenlet spike) | Every benchmark and spike asserts the GIL is still disabled after imports, not only at start-up |
| Thermal throttling on the fanless M2 (added 2026-10-04): it throttles within ~30 s of all-core load and stays throttled after it, and per-process calibration drifts with it, so walls, spreads and task sizes depend on run order and length (`../progress-tracker.md` Experiment 3) | In place: compare walls normalized by each process's measured task size; variants interleaved within a repetition. **Decided 2026-10-04:** P2.2–P2.4 run primarily on the Claude Code cloud container (no throttling seen there, Experiment 4); M2 runs are secondary evidence and are labelled as possibly thermally affected. No thermal guards added to the harness |

## 6. Sign-off decisions

| # | Decision | Answer | Recorded in |
|---|---|---|---|
| 1 | Is a phase with no runtime features acceptable? | Yes (2026-10-04) | This plan, §1 |
| 2 | Commit raw benchmark JSON to the repository? | No (2026-10-04). Scripts, exact commands and recorded environments are committed; raw JSON stays local in a git-ignored folder; summaries go in the tracker | `scope.md` §1, `implementation.md` §2.6 |
| 3 | Runs on a homogeneous-core machine / another OS | The owner will run them separately (2026-10-04). The harness must run unchanged on Linux and macOS; owner-run results are recorded as their own experiments when provided. **Amended 2026-10-04:** the primary environment for P2.2–P2.4 is the Claude Code cloud container (Linux x86_64, homogeneous cores), chosen after the M2 was found to throttle (`../progress-tracker.md` Experiment 3); the M2 is secondary. Runs on the cloud container pin CPython 3.14.7 free-threaded where it can be installed, otherwise record the version difference with every result; the environment is recorded per run because the instance is not guaranteed identical between sessions | `scope.md` §1 and §3, `implementation.md` §2.2 |
| 4 | Decision rules for choosing Phase 3 | **Pending.** Proposed rules in §7; must be accepted or amended before any P2.2–P2.4 result is looked at | §7 |

## 7. Decision rules for Phase 3 — `PROPOSED` (pending sign-off, §6 decision 4)

These are decision criteria, not performance claims. Thresholds are
deliberately set before measurement. "Beyond spread" means the difference
between medians is larger than the larger run-to-run spread of the two
configurations being compared.

1. **Topology first** (per-worker queues and work stealing) if **both**:
   - P2.2: the sharded upper bound's scheduler-only throughput exceeds
     `GlobalQueueScheduler`'s by at least 25% and beyond spread, at 4 or
     more consumers, in streaming mode; **and**
   - P2.4: lock acquisition and hold time inside the scheduler (excluding
     thread wake-ups) is at least 25% of Pyron's per-task overhead with
     0.1 ms tasks (the smallest size in Experiment 1).
2. **Blocking track first** (the option ADR-004 recommends) if rule 1 does
   not fire. A demonstrated correctness limitation outranks an unproven
   performance gain.
3. **Overhead item at the front of Phase 3**, whichever track is chosen, if
   P2.3 shows `ThreadPoolExecutor`'s per-task overhead below Pyron's beyond
   spread, or P2.4 shows a single non-scheduler component (task or handle
   creation, state transitions, completion event) above 25% of per-task
   overhead.
4. **Inconclusive** results (differences inside the spread) count as rule 1
   not firing. The topology question then stays open in
   `architecture-context.md` §5 with the negative or inconclusive evidence
   attached.
5. If runs on a second environment (the M2, or the owner's other
   machines) are available by P2.6 and disagree with the primary cloud
   runs on rule 1, rule 1 does not fire, and the disagreement is recorded
   as a finding. *(Reworded 2026-10-04 when the primary environment moved
   from the M2 to the cloud container, §6 decision 3; intent unchanged.
   Still part of the pending decision 4.)*

## 8. What comes after Phase 2 (not committed)

Phase 3 is whichever track §7 selects; the other becomes the candidate for
Phase 4. The dependency/fan-out benchmark (the owner's original item 2.8)
belongs to the blocking track, because fan-out with waiting needs the
mechanism ADR-004 chooses. Backpressure, running-task cancellation and a
default worker count remain open questions in `architecture-context.md` §5.
Tracked in `../progress-tracker.md` only once actually queued.
