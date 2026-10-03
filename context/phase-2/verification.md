# Phase 2 — Verification

> Status: design-time checks (§1–§4) performed against the written plan on
> 2026-10-04. Execution-time checks (§5) and the completion checklist (§6)
> are pending; they are run as each increment lands. Last updated:
> 2026-10-04.

Two kinds of verification are kept apart: (A) checks that the *plan* is
sound — that each experiment can answer its question and the decision rules
can actually be applied (done on paper); and (B) checks that the
*measurements* are valid when they are run.

## 1. Traceability check (design-time)

### 1.1 The owner's proposed items → this plan

The owner's draft Phase 2 list (2026-10-04) was restructured, not dropped.

| Draft item | Where it is now |
|---|---|
| 2.1 Define task suspension semantics | P2.5 (ADR-004), reframed as "how to handle blocking tasks", with scope B1–B3 decided first |
| 2.2 Cooperative task waiting | Option in ADR-004 (O1/O2/O4); building it is Phase 3 or 4 if the blocking track is chosen |
| 2.3 Task wake-up / continuation scheduling | Criterion 4 in ADR-004; building it is Phase 3 or 4 |
| 2.4 Per-worker queues | Best case measured in P2.2 (variant S); building it is Phase 3 or 4 if `plan.md` §7 rule 1 fires |
| 2.5 Work stealing | Same as 2.4 |
| 2.6 Scheduler contention benchmarks | P2.2 |
| 2.7 CPU workload benchmarks | P2.1 (harness + reproduction) and P2.3 (extended `cpu_saturation.py`) |
| 2.8 Dependency / fan-out benchmarks | Deferred to the blocking track (`plan.md` §8); needs the waiting mechanism first |

### 1.2 Open questions → increments

| Open question (`architecture-context.md` §5) | Addressed by | Expected outcome |
|---|---|---|
| Queue topology | P2.2, P2.4, `plan.md` §7 rule 1 | Evidence for or against building per-worker queues; the question stays open until a second scheduler exists |
| Task granularity | P2.3 (granularity point) | An annotation with a measured, machine-specific figure |
| Task representation (suspension) | P2.5 | ADR-004 `DECIDED` on an approach; question stays open until built |
| Blocking tasks | P2.5 | Same |
| Backpressure, cancellation of running tasks, thread-count policy | Not addressed | Unchanged |

Result: every draft item and every targeted open question has a home; none
is silently dropped.

## 2. Experiment design check (design-time)

| Check | P2.1 | P2.2 | P2.3 | P2.4 |
|---|---|---|---|---|
| States one question | Yes: did the port change the measurement? | Yes | Yes | Yes |
| Records environment (`coding-standards.md` §10) | Yes (harness) | Yes | Yes | Yes |
| Multiple runs, spread reported | 5 reps + warm-up | Same | Same | Same (batched) |
| Verifies results, so a broken run cannot be reported | Yes | Exactly-once delivery check | Yes | Batch outputs checked |
| Has a comparison that isolates Pyron from the machine | `raw`, `procs` | D, Q and S beside G | `raw`, `tpe` beside `pyron` | Bare-deque baseline for lock share; prefilled vs streamed for wake-ups |
| Hang fails rather than blocks | Joins with timeout | Same | Same | Same |
| GIL re-checked after imports | Yes | Yes | Yes | Yes |
| Known limitation stated | Same machine as Experiment 1 | S is an upper bound only | Heterogeneous cores | Components may not add up |

Two design risks found and resolved on paper:

1. *P2.2 variant S could be misread as "what work stealing would deliver".*
   It has no stealing, no close atomicity and no idle parking, so it can
   only overstate the gain. Resolved: it is labelled an upper bound
   everywhere, and `plan.md` §7 rule 1 also requires the P2.4 lock-share
   clause.
2. *Wake-up cost cannot be counted directly without instrumenting `pyron/`,
   which is out of scope.* Resolved: estimated two independent ways
   (hand-off latency in P2.2; prefilled vs streamed end to end in P2.4),
   and the reconciliation reports what remains unexplained.

## 3. Decision-rule check (design-time)

| Check | Result |
|---|---|
| Rules are fixed before the data they use is seen | Required by `plan.md` §6 decision 4; sign-off pending |
| Every rule input is a metric some increment produces | Pass: rule 1 uses P2.2 (S vs G, streaming) and P2.4 (lock share); rule 3 uses P2.3 (`tpe` vs `pyron`) and P2.4 (component shares); rule 5 uses owner-run P2.2/P2.4 repeats |
| Outcomes are exhaustive | Pass: rule 1 fires or rule 2 applies; rule 3 is additive; rule 4 sends inconclusive results to rule 2 |
| Noise is handled explicitly | Pass: "beyond spread" is defined in `plan.md` §7 and computed by the harness (`implementation.md` §2.5) |
| No rule depends on a performance claim in documentation | Pass: thresholds are decision criteria applied to recorded experiments |
| Bias check: the default favours the demonstrated correctness problem, not the speculative speed-up | Intended (rule 2); stated openly so it can be challenged at sign-off |

## 4. Rules compliance (design-time)

| Rule | Source | Result |
|---|---|---|
| Work scoped to the current phase; out-of-scope items listed | `ai-workflow-rules.md` §2 | Pass: `scope.md` §2 |
| No change to `pyron/` | `plan.md` §6 decision 1 | Pass in design; checked again at P2.6 by diff against the phase's start commit |
| No `CONFIRMED` decision altered | `ai-workflow-rules.md` §6 | Pass: ADR-004 is new; it names what a later change would supersede but supersedes nothing itself |
| Every number backed by a committed script, command and environment | `ai-workflow-rules.md` §8 | Pass in design: scripts committed; commands and environments in the tracker; raw JSON local only (`plan.md` §6 decision 2) |
| Benchmarks not in the normal test run | `coding-standards.md` §10 | Pass: only the harness's pure helpers are unit-tested |
| Experiments recorded win, lose or inconclusive | `ai-workflow-rules.md` §5 | Pass in design: every increment, the reproduction run and every spike is an experiment record |
| Experimental code labelled | `ai-workflow-rules.md` §5 | Pass: spikes carry `EXPERIMENTAL:` docstrings and live in `spikes/` |
| Concurrency in benchmark code reasoned about | `coding-standards.md` §3–§4 | Pass: ownership table in `implementation.md` §5 |
| Python-first; no project C extensions | `architecture-context.md` §4 | Pass: greenlet appears only as a spike to answer a factual question |

No violation found.

## 5. Execution-time checks (pending)

| Increment | Checks |
|---|---|
| P2.1 | Harness unit tests pass; full suite still passes; every script's `--quick` runs on the free-threaded build; reproduction run meets the pass condition in `implementation.md` §3.1, or the discrepancy is investigated and recorded before continuing; `benchmarks/results/` is git-ignored |
| P2.2 | Exactly-once delivery holds in every run of every variant; spread recorded per configuration; the tracker entry states that S is an upper bound |
| P2.3 | Default configuration of the extended script still reproduces P2.1's numbers within spread (the extension did not change the defaults); every result verified; granularity point reported per producer count |
| P2.4 | Batch sizes large enough that timer overhead is negligible against the measured time (checked by timing an empty batch); reconciliation and unexplained remainder recorded; profiler used only if confirmed to work on free-threaded 3.14 |
| P2.5 | Every option scored on every criterion; each spike answers its stated question and is recorded; the GIL checked after importing greenlet in K1; owner sign-off recorded |
| P2.6 | `git diff <phase start>..HEAD -- pyron/` is empty; rules applied exactly as signed off; the rule that fired and its inputs recorded; `architecture-context.md` §5 annotated; no document contradicts another |

## 6. Completion checklist

Mirrors `ai-workflow-rules.md` §10, adapted to a phase without runtime code.

- [ ] Work stayed within Phase 2 scope (or expansion was flagged)
- [ ] Nothing in `pyron/` changed; full test suite passes
- [ ] Harness unit tests exist and pass
- [ ] Concurrency in benchmark code was reasoned about, not assumed
- [ ] Every number in any document has a committed script, an exact command and a recorded environment
- [ ] P2.1–P2.4 and every spike recorded in `progress-tracker.md`, including negative or inconclusive results
- [ ] ADR-004 `DECIDED`, or deferred with a recorded reason
- [ ] Phase 3 track chosen by the signed-off rules, with the rule and evidence recorded
- [ ] `architecture-context.md` §5 annotated where Phase 2 produced evidence
- [ ] `progress-tracker.md` reflects the real state (no aspirational entries)
- [ ] No document contradicts another
