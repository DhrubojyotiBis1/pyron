"""Pytest configuration and fixtures for Pyron tests.

All tests require a free-threaded Python build with GIL disabled.
"""

import sys
import pytest


@pytest.fixture(scope="session", autouse=True)
def verify_free_threaded_build():
    """Verify that we're running on a free-threaded build with GIL disabled.

    This is a hard requirement for all Pyron tests. Fail fast if the
    precondition is not met.
    """
    if not hasattr(sys, '_is_gil_enabled'):
        raise RuntimeError(
            "Python version does not support sys._is_gil_enabled(). "
            "Tests require Python 3.13+ to check GIL status."
        )

    if sys._is_gil_enabled():
        raise RuntimeError(
            "Tests must run on a free-threaded Python build with GIL disabled. "
            f"Current build: {sys.version}\n"
            "Use: python3.14t -m pytest (or equivalent free-threaded build)"
        )
