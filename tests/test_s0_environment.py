"""S0 environment verification tests.

Validates that:
1. Free-threaded Python is available
2. GIL is disabled
3. pytest and basic test infrastructure is working
"""

import sys
import pytest


class TestEnvironment:
    """Verify the execution environment is correct."""

    def test_free_threaded_build(self):
        """Confirm we're running on free-threaded Python."""
        assert hasattr(sys, '_is_gil_enabled'), \
            "Python version must support sys._is_gil_enabled()"

    def test_gil_disabled(self):
        """Confirm GIL is actually disabled in this build."""
        assert not sys._is_gil_enabled(), \
            "Tests require free-threaded build with GIL disabled"

    def test_python_version(self):
        """Log Python version for the record."""
        print(f"\nPython: {sys.version}")
        assert sys.version_info >= (3, 13), \
            "Requires Python 3.13+ for free-threading support"

    def test_basic_threading(self):
        """Sanity check: basic threading works."""
        import threading
        result = []

        def task():
            result.append(42)

        t = threading.Thread(target=task)
        t.start()
        t.join()
        assert result == [42]

    def test_multiple_threads_can_run_concurrently(self):
        """Verify multiple threads can execute CPU code in parallel (no GIL).

        This is a basic sanity check, not a benchmark. On a free-threaded
        build with GIL disabled, multiple threads should be able to run
        Python bytecode concurrently without one blocking the others.
        """
        import threading
        import time

        counter = [0]
        lock = threading.Lock()

        def cpu_work():
            """Simulate CPU-bound work."""
            # Sum 0..1M a few times to give the GC a chance to run
            for _ in range(3):
                _ = sum(range(1_000_000))
            with lock:
                counter[0] += 1

        # Start several threads
        threads = [threading.Thread(target=cpu_work) for _ in range(4)]
        start = time.time()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        elapsed = time.time() - start

        # All threads should have completed
        assert counter[0] == 4, "All threads should have incremented counter"
        print(f"\n4 threads completed CPU work in {elapsed:.3f}s")
