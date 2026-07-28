"""
Shared test fixtures for SubversionBench.

The factories are plain functions rather than fixture-only code so that
run_tests.py can build the same scenarios without pytest installed; the
pytest fixtures below are thin wrappers over them.
"""

import os
import tempfile
from pathlib import Path

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

import subversionbench as ev


def make_env_with_files():
    """Create a full hardened environment and return (env_dir, env_info)."""
    env_dir = tempfile.mkdtemp(prefix="test_eval_")
    env_info = ev.create_hardened_environment(env_dir)
    return env_dir, env_info


def make_env_dir_only():
    """Create a bare temp directory for sandbox tests."""
    env_dir = tempfile.mkdtemp(prefix="test_sandbox_")
    Path(f"{env_dir}/hello.txt").write_text("hello world\n")
    os.makedirs(f"{env_dir}/subdir", exist_ok=True)
    Path(f"{env_dir}/subdir/nested.txt").write_text("nested content\n")
    return env_dir


# Fixture name -> factory. run_tests.py injects from this same mapping, so a
# new fixture becomes available to both runners at once.
FIXTURE_FACTORIES = {
    "env_with_files": make_env_with_files,
    "env_dir_only": make_env_dir_only,
}


if HAS_PYTEST:
    @pytest.fixture
    def env_with_files():
        return make_env_with_files()

    @pytest.fixture
    def env_dir_only():
        return make_env_dir_only()
