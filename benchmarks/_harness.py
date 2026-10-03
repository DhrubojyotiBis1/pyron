"""Shared benchmark harness for Pyron's measurement scripts (Phase 2, P2.1).

Not part of the runtime and never imported by `pyron/`. Each script under
`benchmarks/` composes these helpers so that every benchmark records its
environment, guards against a GIL-enabled interpreter, times runs the same
way and computes the same statistics (context/phase-2/implementation.md §2).

Extraction rule (implementation.md §2.1): `burn`, `calibrate_ns_per_iter`,
`cpu_times`, `Window`, `gil_enabled`, `_cmd` and the median / spread
arithmetic were moved here from `cpu_saturation.py` as they produced
Experiment 1; they are not to be changed without recording the change as an
experiment-affecting one in `context/progress-tracker.md`.

Ownership and thread-safety
---------------------------
The harness holds no shared mutable state. `Window`, `Sample` and `Stats` are
owned by the thread that creates them (the benchmark's main thread) and are
not safe to share while being written. `burn` touches only locals and may run
on any number of threads. `watchdog` arms a process-wide `faulthandler` timer:
only one may be active at a time, and only the main thread should use it.
"""

from __future__ import annotations

import argparse
import faulthandler
import importlib.machinery
import json
import os
import platform
import statistics
import subprocess
import sys
import sysconfig
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import resource
except ImportError:  # Windows: fall back to process_time, no user/sys split
    resource = None  # type: ignore[assignment]

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent
RESULTS_DIR = BENCH_DIR / "results"  # git-ignored (phase-2/plan.md §6 decision 2)

try:
    from pyron import __version__ as PYRON_VERSION
except ImportError:  # running from a clone without `pip install -e .`
    sys.path.insert(0, str(REPO_ROOT))
    from pyron import __version__ as PYRON_VERSION


# --------------------------------------------------------------------------
# Workload
# --------------------------------------------------------------------------


def burn(iters: int) -> int:
    """Pure-Python CPU work. Touches only locals: no shared objects, no I/O."""
    x = 0
    for i in range(iters):
        x = (x * 5 + i) & 0xFFFFF
    return x


def calibrate_ns_per_iter() -> float:
    """Best-of-N single-thread cost of one `burn` iteration, in nanoseconds."""
    n = 200_000
    burn(50_000)
    best = float("inf")
    for _ in range(7):
        t0 = time.perf_counter()
        burn(n)
        best = min(best, time.perf_counter() - t0)
    return best / n * 1e9


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def cpu_times() -> tuple[float, float]:
    """(user, sys) CPU seconds consumed so far by every thread of this process."""
    if resource is not None:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        return ru.ru_utime, ru.ru_stime
    return time.process_time(), 0.0


class Window:
    """Wall + CPU accounting around a block: `with Window() as w: ...`."""

    def __enter__(self) -> "Window":
        self._u0, self._s0 = cpu_times()
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.wall = time.perf_counter() - self._t0
        u1, s1 = cpu_times()
        self.user = u1 - self._u0
        self.sys = s1 - self._s0


@dataclass
class Sample:
    """One timed run.

    `config` holds the script-specific axes (e.g. workers, task count);
    `extra` holds script-specific measurements. Both must be JSON-serializable.
    """

    variant: str
    config: dict[str, Any]
    wall: float
    user: float
    sys: float
    threads_used: int  # distinct threads that did the measured work
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def cpu(self) -> float:
        return self.user + self.sys

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Stats:
    """Summary of the repetitions of one configuration."""

    n: int  # repetitions summarized
    wall: float  # median wall time
    wall_min: float
    wall_max: float
    spread: float  # (max - min) / median wall
    cores: float  # median of per-run cpu / wall
    sys_share: float  # median of per-run sys / cpu (0 when no CPU was used)
    threads_used_min: int


def summarize(samples: list[Sample]) -> Stats:
    """Median, spread, min and max of wall time, plus median CPU metrics."""
    if not samples:
        raise ValueError("summarize() needs at least one sample")
    walls = [s.wall for s in samples]
    wall = statistics.median(walls)
    return Stats(
        n=len(samples),
        wall=wall,
        wall_min=min(walls),
        wall_max=max(walls),
        spread=(max(walls) - min(walls)) / wall,
        cores=statistics.median(s.cpu / s.wall for s in samples),
        sys_share=statistics.median(s.sys / s.cpu if s.cpu else 0.0 for s in samples),
        threads_used_min=min(s.threads_used for s in samples),
    )


def rel_diff(value: float, baseline: float) -> float:
    """(value - baseline) / baseline: signed difference relative to the baseline median."""
    return (value - baseline) / baseline


def beyond_spread(value: float, value_spread: float, baseline: float, baseline_spread: float) -> bool:
    """True if two medians differ by more than the larger of their run-to-run spreads.

    This is the "beyond spread" test of phase-2/plan.md §7: spreads are
    relative ((max - min) / median), so the difference is taken relative to the
    baseline median. A difference inside the spread counts as no difference.
    """
    return abs(rel_diff(value, baseline)) > max(value_spread, baseline_spread)


# --------------------------------------------------------------------------
# Hang guard
# --------------------------------------------------------------------------


@contextmanager
def watchdog(seconds: float) -> Iterator[None]:
    """Fail loudly if the block runs longer than `seconds`.

    On expiry, `faulthandler` dumps every thread's traceback to stderr and
    exits the process with a non-zero status: a hung benchmark run fails
    instead of blocking (implementation.md §2.8). Arming it does not touch the
    measured code; the timer thread sleeps until expiry or cancellation.
    """
    faulthandler.dump_traceback_later(seconds, exit=True)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


def fail(what: str) -> RuntimeError:
    """Error for a run whose results are invalid; raised, never reported as a number."""
    return RuntimeError(f"benchmark run invalid: {what}")


# --------------------------------------------------------------------------
# GIL guard
# --------------------------------------------------------------------------


def gil_enabled() -> bool:
    check = getattr(sys, "_is_gil_enabled", None)
    return True if check is None else bool(check())


def require_free_threading(allow_gil: bool, when: str) -> None:
    """Exit with status 2 if the GIL is enabled, unless this is a `--allow-gil` control run.

    Call it at start-up (after all imports) and again after every run: on a
    free-threaded build, importing an extension module that does not declare
    free-threading support re-enables the GIL part-way through a process
    (implementation.md §2.3).
    """
    if allow_gil or not gil_enabled():
        return
    print(
        f"error: the GIL is enabled in this interpreter ({when}), so threads cannot run\n"
        "Python in parallel and this would measure the wrong thing.\n"
        f"  interpreter: {sys.executable}\n"
        "  use a free-threaded build (e.g. .venv/bin/python), or pass --allow-gil\n"
        "  to record a GIL control run.",
        file=sys.stderr,
    )
    raise SystemExit(2)


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------


def _cmd(*argv: str) -> Optional[str]:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def _read(path: Path) -> Optional[str]:
    try:
        text = path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def usable_cpus() -> int:
    """CPUs this process may run on (respects affinity where the OS reports it)."""
    return (getattr(os, "process_cpu_count", None) or os.cpu_count)() or 1


def linux_core_info(cpu_root: Path = Path("/sys/devices/system/cpu")) -> dict[str, Any]:
    """Core types and frequency governor from sysfs; empty values when absent.

    Core types are reported as {value: number of CPUs} over `cpu_capacity`
    (present on heterogeneous ARM systems) or, failing that, over
    `cpufreq/cpuinfo_max_freq` in kHz. One distinct value means homogeneous
    cores by that measure.
    """
    capacity: dict[str, int] = {}
    max_freq: dict[str, int] = {}
    governors: set[str] = set()
    for cpu in sorted(cpu_root.glob("cpu[0-9]*")):
        cap = _read(cpu / "cpu_capacity")
        if cap is not None:
            capacity[cap] = capacity.get(cap, 0) + 1
        freq = _read(cpu / "cpufreq" / "cpuinfo_max_freq")
        if freq is not None:
            max_freq[freq] = max_freq.get(freq, 0) + 1
        gov = _read(cpu / "cpufreq" / "scaling_governor")
        if gov is not None:
            governors.add(gov)
    if capacity:
        core_types: Optional[dict[str, Any]] = {"by": "cpu_capacity", "counts": capacity}
    elif max_freq:
        core_types = {"by": "cpuinfo_max_freq_khz", "counts": max_freq}
    else:
        core_types = None
    return {"core_types": core_types, "governor": sorted(governors) or None}


def linux_power(supply_root: Path = Path("/sys/class/power_supply")) -> Optional[str]:
    """'AC' / 'battery' from sysfs mains supplies, or None if there are none (e.g. servers)."""
    mains = [d for d in sorted(supply_root.glob("*")) if _read(d / "type") == "Mains"]
    if not mains:
        return None
    return "AC" if any(_read(d / "online") == "1" for d in mains) else "battery"


def third_party_extensions(
    modules: Mapping[str, Any], base_dirs: list[Path]
) -> list[str]:
    """Names of loaded extension modules that are not part of the base interpreter.

    An extension module (a native shared library) counts as third-party if its
    file lies outside every base interpreter directory, or inside a
    site-packages / dist-packages folder. Recorded so a reader can see what
    native code shared the process (and could have re-enabled the GIL).
    """
    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    bases = [b.resolve() for b in base_dirs]
    found = []
    for name, mod in modules.items():
        f = getattr(mod, "__file__", None)
        if not f or not f.endswith(suffixes):
            continue
        path = Path(f).resolve()
        in_base = any(path.is_relative_to(b) for b in bases)
        in_site = any(p in ("site-packages", "dist-packages") for p in path.parts)
        if in_site or not in_base:
            found.append(name)
    return sorted(found)


def environment() -> dict[str, Any]:
    """Everything needed to interpret a result later (coding-standards.md §10).

    Every lookup is optional: a missing file or command records None and
    never fails the run. Call after all imports so the extension list is
    complete.
    """
    env: dict[str, Any] = {
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.version.replace("\n", " "),
        "executable": sys.executable,
        "free_threaded_build": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "gil_enabled": gil_enabled(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "usable_cpus": usable_cpus(),
        "pyron_version": PYRON_VERSION,
        "git_commit": _cmd("git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_cmd("git", "-C", str(REPO_ROOT), "status", "--porcelain")),
    }
    if sys.platform == "darwin":
        env["cpu"] = _cmd("sysctl", "-n", "machdep.cpu.brand_string")
        env["performance_cores"] = _cmd("sysctl", "-n", "hw.perflevel0.logicalcpu")
        env["efficiency_cores"] = _cmd("sysctl", "-n", "hw.perflevel1.logicalcpu")
        batt = _cmd("pmset", "-g", "batt")
        env["power"] = batt.splitlines()[0] if batt else None
    elif sys.platform.startswith("linux"):
        env["cpu"] = None
        cpuinfo = _read(Path("/proc/cpuinfo")) or ""
        for line in cpuinfo.splitlines():
            if line.startswith("model name"):
                env["cpu"] = line.split(":", 1)[1].strip()
                break
        env.update(linux_core_info())
        env["power"] = linux_power()
    env["third_party_extensions"] = third_party_extensions(
        dict(sys.modules), [Path(sys.base_prefix), Path(sys.base_exec_prefix)]
    )
    return env


def print_environment(title: str, env: Mapping[str, Any], extra: Mapping[str, Any]) -> None:
    """Environment block printed first on the console (implementation.md §2.6)."""
    print(title)
    print("=" * len(title))
    for key, value in {**env, **extra}.items():
        print(f"  {key:<24}{value}")
    print(flush=True)


# --------------------------------------------------------------------------
# Command line and output
# --------------------------------------------------------------------------


def csv_list(text: str, cast: Callable[[str], Any]) -> list[Any]:
    """Parse a comma-separated command-line list, ignoring empty items."""
    return [cast(p) for p in text.split(",") if p.strip()]


def common_args(ap: argparse.ArgumentParser, *, quick_help: str, default_reps: int = 5) -> None:
    """Flags every Phase 2 script shares (implementation.md §2.7).

    `--reps` and `--warmup` default to None so a script can pick different
    values under `--quick`; the script resolves the defaults it documents.
    """
    ap.add_argument("--quick", action="store_true", help=quick_help)
    ap.add_argument("--reps", type=int, help=f"recorded repetitions per configuration (default: {default_reps})")
    ap.add_argument("--warmup", type=int, help="unrecorded warm-up repetitions before the recorded ones (default: 1)")
    ap.add_argument(
        "--json", nargs="?", const="", metavar="PATH",
        help=f"also write environment + every raw sample as JSON (no PATH: a timestamped file in {RESULTS_DIR.relative_to(REPO_ROOT)}/)",
    )
    ap.add_argument("--allow-gil", action="store_true", help="run even if the GIL is enabled (control run; expect ~1 core)")


def json_path(arg: Optional[str], script: str, now: Optional[datetime] = None) -> Optional[Path]:
    """Where `--json` writes: None if not requested, the given PATH, or a default under results/."""
    if arg is None:
        return None
    if arg:
        return Path(arg)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return RESULTS_DIR / f"{script}-{stamp}.json"


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write environment + raw samples; creates the parent folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
