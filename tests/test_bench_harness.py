"""Unit tests for the benchmark harness's pure helpers (Phase 2, P2.1).

These test the measuring tool, not Pyron, and run no benchmark: everything
here is fast and deterministic (coding-standards.md §10 keeps benchmarks out
of the test run; phase-2/scope.md §1 allows tests of the harness).
"""

import argparse
import json
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

BENCH_DIR = Path(__file__).resolve().parent.parent / "benchmarks"
sys.path.insert(0, str(BENCH_DIR))

import _harness as h  # noqa: E402


def _sample(wall: float, user: float = 0.0, sys_: float = 0.0, used: int = 1) -> h.Sample:
    return h.Sample("v", {"workers": 1}, wall, user, sys_, used)


class TestSummarize:
    def test_median_spread_min_max_odd(self):
        st = h.summarize([_sample(1.0), _sample(3.0), _sample(2.0)])
        assert st.n == 3
        assert st.wall == 2.0
        assert st.wall_min == 1.0
        assert st.wall_max == 3.0
        assert st.spread == pytest.approx(1.0)  # (3 - 1) / 2

    def test_median_even_count(self):
        st = h.summarize([_sample(1.0), _sample(2.0), _sample(4.0), _sample(5.0)])
        assert st.wall == 3.0
        assert st.spread == pytest.approx(4.0 / 3.0)

    def test_single_sample_has_zero_spread(self):
        st = h.summarize([_sample(2.5, user=2.5)])
        assert st.wall == 2.5
        assert st.spread == 0.0

    def test_cores_and_sys_share_are_medians_of_per_run_ratios(self):
        st = h.summarize([
            _sample(1.0, user=3.0, sys_=1.0),   # cores 4, sys 25%
            _sample(2.0, user=2.0, sys_=0.0),   # cores 1, sys 0%
            _sample(1.0, user=1.5, sys_=0.5),   # cores 2, sys 25%
        ])
        assert st.cores == pytest.approx(2.0)
        assert st.sys_share == pytest.approx(0.25)

    def test_zero_cpu_gives_zero_sys_share(self):
        st = h.summarize([_sample(1.0, user=0.0, sys_=0.0)])
        assert st.sys_share == 0.0
        assert st.cores == 0.0

    def test_threads_used_min(self):
        st = h.summarize([_sample(1.0, used=4), _sample(1.0, used=3), _sample(1.0, used=4)])
        assert st.threads_used_min == 3

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            h.summarize([])

    def test_matches_experiment_1_arithmetic(self):
        """The generalized summary computes what cpu_saturation's Stats did in Experiment 1."""
        samples = [_sample(0.85, 6.0, 0.05), _sample(0.80, 5.5, 0.04), _sample(0.92, 6.4, 0.06)]
        walls = [0.85, 0.80, 0.92]
        st = h.summarize(samples)
        assert st.wall == 0.85
        assert st.spread == pytest.approx((max(walls) - min(walls)) / 0.85)


class TestBeyondSpread:
    def test_rel_diff_signed(self):
        assert h.rel_diff(1.1, 1.0) == pytest.approx(0.1)
        assert h.rel_diff(0.9, 1.0) == pytest.approx(-0.1)

    def test_inside_larger_spread_is_not_beyond(self):
        # 10% apart; the larger spread is 12%
        assert not h.beyond_spread(1.10, 0.02, 1.00, 0.12)
        assert not h.beyond_spread(1.10, 0.12, 1.00, 0.02)

    def test_outside_both_spreads_is_beyond(self):
        assert h.beyond_spread(1.10, 0.05, 1.00, 0.03)
        assert h.beyond_spread(0.90, 0.05, 1.00, 0.03)

    def test_equal_to_spread_is_not_beyond(self):
        assert not h.beyond_spread(1.25, 0.0, 1.00, 0.25)

    def test_zero_spreads_any_difference_is_beyond(self):
        assert h.beyond_spread(1.001, 0.0, 1.0, 0.0)
        assert not h.beyond_spread(1.0, 0.0, 1.0, 0.0)


class TestSample:
    def test_cpu_and_json_roundtrip(self):
        s = h.Sample("raw", {"workers": 4, "n_tasks": 10}, 1.0, 2.0, 0.5, 4, {"x": 1})
        assert s.cpu == 2.5
        d = s.to_json()
        assert d == {
            "variant": "raw", "config": {"workers": 4, "n_tasks": 10}, "wall": 1.0,
            "user": 2.0, "sys": 0.5, "threads_used": 4, "extra": {"x": 1},
        }
        json.dumps(d)  # serializable


class TestWorkloadAndWindow:
    def test_burn_is_deterministic(self):
        assert h.burn(0) == 0
        assert h.burn(1000) == h.burn(1000)
        assert h.burn(3) == ((((0 * 5 + 0) * 5 + 1) * 5 + 2) & 0xFFFFF)

    def test_window_records_nonnegative_times(self):
        with h.Window() as w:
            h.burn(10_000)
        assert w.wall > 0
        assert w.user >= 0 and w.sys >= 0


class TestGilGuard:
    def test_gil_enabled_reads_interpreter(self, monkeypatch):
        monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
        assert h.gil_enabled() is True
        monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False, raising=False)
        assert h.gil_enabled() is False

    def test_missing_check_counts_as_enabled(self, monkeypatch):
        monkeypatch.delattr(sys, "_is_gil_enabled", raising=False)
        assert h.gil_enabled() is True

    def test_require_exits_2_when_enabled(self, monkeypatch, capsys):
        monkeypatch.setattr(h, "gil_enabled", lambda: True)
        with pytest.raises(SystemExit) as exc:
            h.require_free_threading(False, "after a test run")
        assert exc.value.code == 2
        assert "after a test run" in capsys.readouterr().err

    def test_require_allows_control_run(self, monkeypatch):
        monkeypatch.setattr(h, "gil_enabled", lambda: True)
        h.require_free_threading(True, "control")  # no exit

    def test_require_passes_when_disabled(self, monkeypatch):
        monkeypatch.setattr(h, "gil_enabled", lambda: False)
        h.require_free_threading(False, "start")


class TestEnvironment:
    def test_linux_core_info_by_capacity(self, tmp_path):
        for i, cap in enumerate(["1024", "1024", "512", "512", "512"]):
            d = tmp_path / f"cpu{i}"
            (d / "cpufreq").mkdir(parents=True)
            (d / "cpu_capacity").write_text(cap + "\n")
            (d / "cpufreq" / "cpuinfo_max_freq").write_text("3000000\n")
            (d / "cpufreq" / "scaling_governor").write_text("performance\n")
        (tmp_path / "cpufreq").mkdir()  # not a cpuN directory: ignored
        info = h.linux_core_info(tmp_path)
        assert info["core_types"] == {"by": "cpu_capacity", "counts": {"1024": 2, "512": 3}}
        assert info["governor"] == ["performance"]

    def test_linux_core_info_falls_back_to_max_freq(self, tmp_path):
        for i, f in enumerate(["3200000", "2400000", "3200000"]):
            d = tmp_path / f"cpu{i}" / "cpufreq"
            d.mkdir(parents=True)
            (d / "cpuinfo_max_freq").write_text(f)
        info = h.linux_core_info(tmp_path)
        assert info["core_types"] == {"by": "cpuinfo_max_freq_khz", "counts": {"2400000": 1, "3200000": 2}}
        assert info["governor"] is None

    def test_linux_core_info_missing_sysfs(self, tmp_path):
        assert h.linux_core_info(tmp_path / "absent") == {"core_types": None, "governor": None}

    def test_linux_power(self, tmp_path):
        assert h.linux_power(tmp_path) is None
        (tmp_path / "BAT0").mkdir()
        (tmp_path / "BAT0" / "type").write_text("Battery")
        assert h.linux_power(tmp_path) is None
        (tmp_path / "AC").mkdir()
        (tmp_path / "AC" / "type").write_text("Mains")
        (tmp_path / "AC" / "online").write_text("0")
        assert h.linux_power(tmp_path) == "battery"
        (tmp_path / "AC" / "online").write_text("1")
        assert h.linux_power(tmp_path) == "AC"

    def test_third_party_extensions(self, tmp_path):
        base = tmp_path / "base"
        so = h.importlib.machinery.EXTENSION_SUFFIXES[0]
        mods = {
            "stdlib_ext": types.SimpleNamespace(__file__=str(base / "lib" / "lib-dynload" / f"_x{so}")),
            "site_ext": types.SimpleNamespace(__file__=str(base / "lib" / "site-packages" / f"g{so}")),
            "venv_ext": types.SimpleNamespace(__file__=str(tmp_path / "venv" / f"v{so}")),
            "pure": types.SimpleNamespace(__file__=str(tmp_path / "venv" / "p.py")),
            "builtin": types.SimpleNamespace(),
            "none_file": types.SimpleNamespace(__file__=None),
        }
        assert h.third_party_extensions(mods, [base]) == ["site_ext", "venv_ext"]

    def test_environment_never_fails_without_commands(self, monkeypatch):
        monkeypatch.setattr(h, "_cmd", lambda *argv: None)
        env = h.environment()
        for key in ("date", "python", "free_threaded_build", "gil_enabled", "os", "logical_cpus",
                    "usable_cpus", "pyron_version", "git_commit", "git_dirty", "third_party_extensions"):
            assert key in env
        assert env["git_commit"] is None
        assert env["usable_cpus"] >= 1
        json.dumps(env)  # serializable

    def test_environment_on_this_interpreter(self):
        env = h.environment()
        assert env["free_threaded_build"] is True
        assert env["gil_enabled"] is False
        assert isinstance(env["third_party_extensions"], list)


class TestCommandLine:
    def test_csv_list(self):
        assert h.csv_list("1,2, 4,", int) == [1, 2, 4]
        assert h.csv_list("0.1,10", float) == [0.1, 10.0]

    def _parse(self, argv):
        ap = argparse.ArgumentParser()
        h.common_args(ap, quick_help="q")
        return ap.parse_args(argv)

    def test_common_args_defaults(self):
        a = self._parse([])
        assert (a.quick, a.reps, a.warmup, a.json, a.allow_gil) == (False, None, None, None, False)

    def test_common_args_json_with_and_without_path(self):
        assert self._parse(["--json"]).json == ""
        assert self._parse(["--json", "x.json"]).json == "x.json"
        a = self._parse(["--quick", "--reps", "3", "--warmup", "0", "--allow-gil"])
        assert (a.quick, a.reps, a.warmup, a.allow_gil) == (True, 3, 0, True)

    def test_json_path(self):
        assert h.json_path(None, "s") is None
        assert h.json_path("out/x.json", "s") == Path("out/x.json")
        p = h.json_path("", "cpu_saturation", now=datetime(2026, 10, 4, 3, 5, 9))
        assert p == h.RESULTS_DIR / "cpu_saturation-20261004-030509.json"

    def test_write_json_creates_parent(self, tmp_path):
        out = tmp_path / "a" / "b.json"
        h.write_json(out, {"k": [1, 2]})
        assert json.loads(out.read_text()) == {"k": [1, 2]}

    def test_results_dir_is_git_ignored(self):
        root = BENCH_DIR.parent
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "benchmarks/results/x.json"])
        assert r.returncode == 0


class TestWatchdog:
    def test_disarmed_after_block(self):
        with h.watchdog(0.2):
            pass
        import time
        time.sleep(0.4)  # would have fired (and killed pytest) if still armed

    def test_hang_fails_loudly(self):
        code = (
            f"import sys, threading; sys.path.insert(0, {str(BENCH_DIR)!r}); import _harness as h\n"
            "with h.watchdog(0.3):\n"
            "    threading.Event().wait()\n"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        assert r.returncode != 0
        assert "Timeout" in r.stderr
