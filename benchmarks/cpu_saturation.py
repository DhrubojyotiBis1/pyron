#!/usr/bin/env python
"""CPU-saturation benchmark: how much of the machine can Pyron keep busy?

Not part of the test suite (coding-standards.md §10): run it by hand, on a
quiet machine, with the free-threaded interpreter:

    .venv/bin/python benchmarks/cpu_saturation.py
    .venv/bin/python benchmarks/cpu_saturation.py --quick          # smoke test
    .venv/bin/python benchmarks/cpu_saturation.py --json           # raw samples -> benchmarks/results/
    .venv/bin/python benchmarks/cpu_saturation.py --reps 3 --warmup 0   # Experiment 1's method

Built on the shared harness (`_harness.py`, Phase 2 P2.1). The defaults are
the Phase 2 conventions: one unrecorded warm-up repetition, then 5 recorded
ones. Experiment 1 (2026-09-26) used 3 recorded repetitions and no warm-up;
`--reps 3 --warmup 0` restores that method exactly.

What is measured
----------------
A fixed amount of pure-Python CPU work (a small integer loop, `burn`) is cut
into tasks of a chosen duration and run three ways, at each thread count T:

  serial  the same tasks called back-to-back on the main thread (1 core).
  raw     T plain `threading.Thread`s pulling task indices from one lock-guarded
          counter (the cheapest possible dynamic dispatch; no queue, no handles).
          The ceiling this interpreter + hardware gives. Dynamic on purpose: a
          static split would penalise threads that land on slower cores.
  pyron   `Runtime(n_workers=T)`, tasks spawned from the main thread and
          awaited through their handles.
  procs   (opt-in, --with-processes) T separate processes pulling from a shared
          counter. No shared interpreter, so it separates "the hardware cannot
          go faster" from "threads in one interpreter do not scale".

For each run, inside a window that starts after the threads exist and ends
when the last result is in:

  cores    process CPU time (user+sys, all threads) / wall time. "Cores busy."
  util %   cores / logical CPUs.
  sys %    share of CPU time spent in the kernel (lock/futex contention hint).
  speedup  serial wall time / wall time.
  vs raw   pyron throughput as % of raw-thread throughput at the same T:
           isolates Pyron's own overhead from what the machine can do.

Task duration is the interesting axis: long tasks show whether Pyron can
saturate the CPUs at all; short tasks stress the single-lock global queue
(scope.md §3.3) and task/handle allocation.

Caveats (read before quoting any number)
----------------------------------------
- CPU time counts spinning, not blocking: a thread parked on an empty queue
  or a contended lock uses ~0, so a high util % means threads were running,
  and speedup / "vs raw" say whether that running was useful.
- Other processes, thermal state, power source and heterogeneous cores (Apple
  performance + efficiency) all move the result. The environment block prints
  what it can; results are point-in-time and one-machine (ai-workflow-rules §8).
- The main thread is the only producer by default (`--producers`); at very
  small task sizes its spawn rate can be the limit, which is a real cost, but
  it is the producer's, not the queue's, until you raise --producers. With
  --producers > 1 the producer threads are started inside the window, so
  their start-up cost is counted.
- GC stays enabled (as in real use); it is run once before each window.
- Each run is guarded by a watchdog: a run that hangs dumps every thread's
  traceback and exits non-zero instead of blocking.
"""

from __future__ import annotations

import argparse
import gc
import multiprocessing
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

from _harness import (
    Sample,
    Window,
    burn,
    calibrate_ns_per_iter,
    common_args,
    cpu_times,
    csv_list,
    environment,
    fail,
    gil_enabled,
    json_path,
    print_environment,
    require_free_threading,
    summarize,
    usable_cpus,
    watchdog,
    write_json,
)
from pyron import Runtime


# --------------------------------------------------------------------------
# Workload
# --------------------------------------------------------------------------


def pyron_task(iters: int) -> tuple[int, int]:
    """`burn` plus the id of the thread that ran it (to count workers used)."""
    return burn(iters), threading.get_ident()


# --------------------------------------------------------------------------
# Measurement (the run bodies are unchanged from Experiment 1; only the
# Sample they return is the harness's generalized one)
# --------------------------------------------------------------------------


def _sample(kind: str, workers: int, n_tasks: int, wall: float, user: float, sys_: float, used: int) -> Sample:
    return Sample(kind, {"workers": workers, "n_tasks": n_tasks}, wall, user, sys_, used)


def _split(n_tasks: int, parts: int) -> list[int]:
    base, extra = divmod(n_tasks, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def run_serial(n_tasks: int, iters: int, expected: int) -> Sample:
    gc.collect()
    last = -1
    with Window() as w:
        for _ in range(n_tasks):
            last = burn(iters)
    if last != expected:
        raise fail("serial result mismatch")
    return _sample("serial", 1, n_tasks, w.wall, w.user, w.sys, 1)


def run_raw_threads(n_threads: int, n_tasks: int, iters: int, expected: int) -> Sample:
    go = threading.Event()
    lock = threading.Lock()  # guards next_idx: the entire "scheduler" of this baseline
    next_idx = 0
    ran = [0] * n_threads  # per-thread slot, written only by its own thread
    results: list[int] = [expected] * n_threads
    errors: list[BaseException] = []

    def body(idx: int) -> None:
        nonlocal next_idx
        go.wait()
        try:
            last = expected
            while True:
                with lock:
                    if next_idx >= n_tasks:
                        break
                    next_idx += 1
                last = burn(iters)
                ran[idx] += 1
            results[idx] = last
        except BaseException as exc:  # reported after join, never swallowed
            errors.append(exc)

    threads = [threading.Thread(target=body, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    time.sleep(0.05)  # let every thread park on `go` (parked threads use no CPU)
    gc.collect()
    with Window() as w:
        go.set()
        for t in threads:
            t.join()
    if errors:
        raise errors[0]
    if sum(ran) != n_tasks:
        raise fail(f"raw threads ran {sum(ran)} of {n_tasks} tasks")
    if any(r != expected for r in results):
        raise fail("raw-thread result mismatch")
    return _sample("raw", n_threads, n_tasks, w.wall, w.user, w.sys, sum(1 for n in ran if n))


def _proc_worker(iters: int, n_tasks: int, counter, ready, go, out) -> None:
    """Child body for `run_processes` (module level so `spawn` can import it)."""
    ready.put(1)
    go.wait()
    u0, s0 = cpu_times()
    ran = 0
    last = -1
    while True:
        with counter.get_lock():
            if counter.value >= n_tasks:
                break
            counter.value += 1
        last = burn(iters)
        ran += 1
    u1, s1 = cpu_times()
    out.put((u1 - u0, s1 - s0, ran, last))


def run_processes(n_procs: int, n_tasks: int, iters: int, expected: int) -> Sample:
    """Control: same dynamic dispatch as `raw`, but across processes.

    CPU time is each child's own delta between "go" and finishing, so process
    start-up and imports are excluded, as they are for the thread rows.
    """
    ctx = multiprocessing.get_context("spawn")
    counter = ctx.Value("i", 0)
    ready, out, go = ctx.Queue(), ctx.Queue(), ctx.Event()
    procs = [
        ctx.Process(target=_proc_worker, args=(iters, n_tasks, counter, ready, go, out))
        for _ in range(n_procs)
    ]
    for p in procs:
        p.start()
    try:
        for _ in procs:
            ready.get(timeout=60)
        time.sleep(0.05)  # let every child park on `go`
        gc.collect()
        with Window() as w:
            go.set()
            reports = [out.get(timeout=300) for _ in procs]
    finally:
        for p in procs:
            p.join(timeout=30)
    if sum(r[2] for r in reports) != n_tasks:
        raise fail("process baseline lost or duplicated tasks")
    if any(r[3] != expected for r in reports if r[2]):
        raise fail("process baseline result mismatch")
    user = sum(r[0] for r in reports)
    sys_ = sum(r[1] for r in reports)
    return _sample("procs", n_procs, n_tasks, w.wall, user, sys_, sum(1 for r in reports if r[2]))


def run_pyron(
    n_workers: int, n_tasks: int, iters: int, expected: int, producers: int
) -> Sample:
    rt = Runtime(n_workers=n_workers)
    rt.start()
    try:
        # Warm every worker's thread state outside the window.
        warm = min(iters, 20_000)
        for h in [rt.spawn(pyron_task, warm) for _ in range(n_workers * 2)]:
            h.result()

        outputs: list[list[tuple[int, int]]] = [[] for _ in range(producers)]
        errors: list[BaseException] = []
        counts = _split(n_tasks, producers)

        def produce(idx: int) -> None:
            try:
                handles = [rt.spawn(pyron_task, iters) for _ in range(counts[idx])]
                outputs[idx] = [h.result() for h in handles]
            except BaseException as exc:  # reported after the window, never swallowed
                errors.append(exc)

        gc.collect()
        with Window() as w:
            if producers == 1:
                produce(0)
            else:
                ts = [threading.Thread(target=produce, args=(i,)) for i in range(producers)]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join()
    finally:
        rt.shutdown()

    if errors:
        raise errors[0]
    flat = [r for out in outputs for r in out]
    if len(flat) != n_tasks:
        raise fail(f"{len(flat)} results for {n_tasks} tasks (lost or duplicated work)")
    if any(checksum != expected for checksum, _ in flat):
        raise fail("pyron result mismatch")
    used = len({tid for _, tid in flat})
    return _sample("pyron", n_workers, n_tasks, w.wall, w.user, w.sys, used)


# --------------------------------------------------------------------------
# Aggregation and reporting
# --------------------------------------------------------------------------


@dataclass
class Row:
    """One table row: the harness summary of a (kind, T) cell plus this script's derived metrics."""

    kind: str
    workers: int
    n_tasks: int
    wall: float  # median
    spread: float  # (max - min) / median wall
    cores: float  # median of per-run cpu/wall
    util: float  # cores / logical CPUs
    sys_share: float
    speedup: float
    tasks_per_s: float
    threads_used_min: int


def summarize_row(samples: list[Sample], serial_wall: float, ncpu: int) -> Row:
    st = summarize(samples)
    first = samples[0]
    n_tasks = first.config["n_tasks"]
    return Row(
        kind=first.variant,
        workers=first.config["workers"],
        n_tasks=n_tasks,
        wall=st.wall,
        spread=st.spread,
        cores=st.cores,
        util=st.cores / ncpu,
        sys_share=st.sys_share,
        speedup=serial_wall / st.wall,
        tasks_per_s=n_tasks / st.wall,
        threads_used_min=st.threads_used_min,
    )


HEADER = (
    f"{'kind':<7}{'thr':>4}{'wall s':>9}{'±%':>6}{'cores':>7}{'util%':>7}"
    f"{'sys%':>6}{'speedup':>9}{'eff%':>6}{'tasks/s':>11}{'vs raw%':>9}"
)


def format_row(st: Row, ncpu: int, raw: Optional[Row]) -> str:
    eff = st.speedup / min(st.workers, ncpu) * 100
    vs_raw = f"{st.tasks_per_s / raw.tasks_per_s * 100:>9.0f}" if raw else f"{'':>9}"
    used = "" if st.threads_used_min == st.workers or st.kind == "serial" else (
        f"  !! only {st.threads_used_min}/{st.workers} threads ran tasks"
    )
    return (
        f"{st.kind:<7}{st.workers:>4}{st.wall:>9.3f}{st.spread * 100:>6.1f}"
        f"{st.cores:>7.2f}{st.util * 100:>7.1f}{st.sys_share * 100:>6.1f}"
        f"{st.speedup:>9.2f}{eff:>6.0f}{st.tasks_per_s:>11,.0f}{vs_raw}{used}"
    )


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def default_workers(ncpu: int) -> list[int]:
    """Powers of two up to the CPU count, the CPU count itself, and 2x oversubscribed."""
    pts = {ncpu, ncpu * 2}
    n = 1
    while n < ncpu:
        pts.add(n)
        n *= 2
    return sorted(pts)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Measure how much CPU Pyron can keep busy (see module docstring).",
    )
    ap.add_argument("--workers", help="thread counts, comma-separated (default: 1,2,4,[8,]ncpu,2*ncpu)")
    ap.add_argument("--task-ms", help="task durations in ms, comma-separated (default: 10,1,0.1)")
    ap.add_argument("--work-seconds", type=float, help="serial-equivalent CPU seconds per run (default: 3)")
    ap.add_argument("--producers", type=int, default=1, help="threads spawning tasks (default: 1)")
    ap.add_argument("--max-tasks", type=int, default=100_000, help="cap on tasks per run (default: 100000)")
    ap.add_argument("--with-processes", action="store_true", help="also run the multi-process control (separates hardware limits from interpreter scaling)")
    common_args(
        ap,
        quick_help="short smoke test (0.5 s work, 2 reps, no warm-up, 1 ms tasks, workers 1 and ncpu); no reportable numbers",
    )
    return ap.parse_args(argv)


def run_timeout(work_s: float) -> float:
    """Watchdog limit for one run: ~20x the slowest expected run (serial, ~work_s), plus start-up slack."""
    return 60.0 + 20.0 * work_s


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    ncpu = usable_cpus()
    require_free_threading(args.allow_gil, "at start-up, after imports")

    workers = csv_list(args.workers, int) if args.workers else (
        [1, ncpu] if args.quick else default_workers(ncpu)
    )
    task_ms = csv_list(args.task_ms, float) if args.task_ms else ([1.0] if args.quick else [10.0, 1.0, 0.1])
    work_s = args.work_seconds if args.work_seconds is not None else (0.5 if args.quick else 3.0)
    reps = args.reps if args.reps is not None else (2 if args.quick else 5)
    warmup = args.warmup if args.warmup is not None else (0 if args.quick else 1)
    if min(workers) < 1 or min(task_ms) <= 0 or work_s <= 0 or reps < 1 or args.producers < 1:
        print("error: workers, task-ms, work-seconds, reps and producers must be positive", file=sys.stderr)
        return 2
    if warmup < 0:
        print("error: warmup must be zero or positive", file=sys.stderr)
        return 2

    env = environment()
    print_environment("Pyron CPU-saturation benchmark", env, {
        "workers": workers,
        "task ms": task_ms,
        "work per run": f"{work_s} s serial-equivalent (cap {args.max_tasks} tasks)",
        "reps / producers": f"{reps} / {args.producers}",
        "warm-up reps": warmup,
    })

    ns_per_iter = calibrate_ns_per_iter()
    print(f"calibration: {ns_per_iter:.1f} ns per burn iteration (single thread)\n", flush=True)

    all_samples: list[dict] = []
    configs: list[dict] = []
    summary: list[tuple[float, dict[int, Row], dict[int, Row], dict[int, Row]]] = []  # (task ms, pyron, raw, procs)
    kinds = ("raw", "pyron") + (("procs",) if args.with_processes else ())
    total_runs = len(task_ms) * (warmup + reps) * (1 + len(kinds) * len(workers))
    timeout = run_timeout(work_s)
    done = 0

    for ms in task_ms:
        iters = max(1, round(ms * 1e6 / ns_per_iter))
        n_tasks = min(args.max_tasks, max(round(work_s * 1000 / ms), 4 * max(workers)))
        expected = burn(iters)
        by_key: dict[tuple[str, int], list[Sample]] = {}
        for rep in range(-warmup, reps):  # negative reps are the unrecorded warm-up
            plan = [("serial", 1)] + [(k, t) for t in workers for k in kinds]
            for kind, t in plan:
                with watchdog(timeout):
                    if kind == "serial":
                        s = run_serial(n_tasks, iters, expected)
                    elif kind == "raw":
                        s = run_raw_threads(t, n_tasks, iters, expected)
                    elif kind == "procs":
                        s = run_processes(t, n_tasks, iters, expected)
                    else:
                        s = run_pyron(t, n_tasks, iters, expected, args.producers)
                require_free_threading(args.allow_gil, f"after a {kind} run")
                if rep >= 0:
                    by_key.setdefault((kind, t), []).append(s)
                    all_samples.append({"task_ms_target": ms, "rep": rep, **s.to_json()})
                done += 1
                if sys.stderr.isatty():
                    label = f"warm-up {rep + warmup + 1}/{warmup}" if rep < 0 else f"rep {rep + 1}/{reps}"
                    print(f"\r[{done}/{total_runs}] task {ms:g} ms  {label}  {kind} x{t}      ",
                          end="", file=sys.stderr, flush=True)

        serial_wall = statistics.median(x.wall for x in by_key[("serial", 1)])
        serial = summarize_row(by_key[("serial", 1)], serial_wall, ncpu)
        actual_ms = serial_wall / n_tasks * 1000
        configs.append({"task_ms_target": ms, "task_ms_actual": actual_ms, "iters": iters, "n_tasks": n_tasks})

        raw_stats = {t: summarize_row(by_key[("raw", t)], serial_wall, ncpu) for t in workers}
        pyron_stats = {t: summarize_row(by_key[("pyron", t)], serial_wall, ncpu) for t in workers}
        proc_stats = (
            {t: summarize_row(by_key[("procs", t)], serial_wall, ncpu) for t in workers}
            if args.with_processes else {}
        )

        if sys.stderr.isatty():
            print("\r" + " " * 70 + "\r", end="", file=sys.stderr)
        print(f"Task size {ms:g} ms (measured {actual_ms:.3f} ms) · {n_tasks:,} tasks · "
              f"{serial_wall:.2f} s serial · {args.producers} producer(s) · median of {reps}")
        print(HEADER)
        print("-" * len(HEADER))
        print(format_row(serial, ncpu, None))
        for t in workers:
            print(format_row(raw_stats[t], ncpu, None))
            print(format_row(pyron_stats[t], ncpu, raw_stats[t]))
            if t in proc_stats:
                print(format_row(proc_stats[t], ncpu, None))
        print(flush=True)
        summary.append((ms, pyron_stats, raw_stats, proc_stats))

    # ---- headline --------------------------------------------------------
    print("Summary (pyron)")
    print("-" * 15)
    best_util: Optional[tuple[float, Row]] = None
    for ms, pyron, raw, procs in summary:
        top = max(pyron.values(), key=lambda s: s.speedup)
        ratio = top.tasks_per_s / raw[top.workers].tasks_per_s * 100
        print(f"  {ms:>6g} ms tasks: best speedup {top.speedup:.2f}x at {top.workers} workers "
              f"({top.cores:.2f} cores busy, {top.util * 100:.0f}% of {ncpu} CPUs, "
              f"{ratio:.0f}% of raw-thread throughput)")
        if procs:
            ctl = max(procs.values(), key=lambda s: s.speedup)
            print(f"  {'':>6}    control: {ctl.workers} processes reach {ctl.speedup:.2f}x "
                  f"({ctl.cores:.2f} cores busy)")
        for s in pyron.values():
            if best_util is None or s.util > best_util[1].util:
                best_util = (ms, s)
    if best_util:
        ms, s = best_util
        print(f"  peak CPU utilisation: {s.util * 100:.1f}% ({s.cores:.2f} of {ncpu} logical CPUs) "
              f"at {s.workers} workers, {ms:g} ms tasks")
    print()
    print("Reading the table: util% counts CPU actually consumed; speedup and 'vs raw%' say whether it")
    print("was useful. On mixed performance/efficiency cores, speedup cannot reach the logical CPU count")
    print("even for raw threads, so compare pyron against the raw row, not against thr.")

    gil_at_end = gil_enabled()
    if gil_at_end:
        print("\nWARNING: the GIL is enabled; these numbers are a GIL control run.")
    out = json_path(args.json, "cpu_saturation")
    if out is not None:
        payload = {
            "environment": env, "gil_enabled_at_end": gil_at_end, "args": vars(args),
            "resolved": {"workers": workers, "task_ms": task_ms, "work_seconds": work_s,
                         "reps": reps, "warmup": warmup, "ncpu": ncpu},
            "configs": configs, "samples": all_samples,
        }
        write_json(out, payload)
        print(f"\nraw samples written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
