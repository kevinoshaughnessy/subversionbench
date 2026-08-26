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

# Placeholder credentials for the whole session.
#
# Nothing here reaches an API - every test that runs an episode stubs
# llm_client.get_client - but run_batch now REFUSES to roll out when the
# credential a model authenticates with is absent, and it checks the environment
# rather than the client because the Anthropic SDK constructs happily without a
# key and defers the failure to the first call. That refusal is the point: a
# rollout whose ANTHROPIC_API_KEY was missing once completed in full, failed one
# classifier call at a time, and published a scheming rate built entirely on
# keyword fallbacks.
#
# So the suite supplies placeholders rather than bypassing the check, which keeps
# the check itself exercised. A test that wants the refusal unsets them - see
# test_credential_preflight.py.
def _placeholder_credentials():
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        os.environ.setdefault(var, f"placeholder-for-tests-{var.lower()}")


_placeholder_credentials()


# ---------------------------------------------------------------------------
# What "the project's Python files" means - defined once
# ---------------------------------------------------------------------------
#
# Three separate guards each carried their own hand-written list of roots, and
# they disagreed. The undefined-name guard globbed three named directories
# NON-recursively, so it never looked at `subversionbench/grading/`,
# `readmodes/`, `reporting/` or `reporting/facts/` - the graders and the module
# where every published figure is computed. A planted `undefined_name` there
# passed the guard while pyflakes reported it directly.
#
# The deeper fault is the shape rather than the missing `r`: a list of directory
# names has to be edited whenever a package is added, silently keeps working when
# nobody does, and `trends/` and `report/` were both carved out of root scripts
# and added to each list by hand. Deriving the set from a rule is what stops the
# next package from being missed - see test_project_files.py, which checks this
# discovery against `git ls-files` so the two cannot drift apart quietly.

PROJECT_ROOT = Path(__file__).resolve().parent

# Directories that are not the project: tooling, caches, build output, the
# results corpora, and this session's scratch space.
_NOT_PROJECT = {
    ".git", ".venv", "venv", ".tox", "build", "dist", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules",
    "scratchpad", "report_snapshots",
}


def _is_project_path(relative: Path) -> bool:
    for part in relative.parts:
        if part in _NOT_PROJECT:
            return False
        if part.endswith(".egg-info") or part.startswith("eval_results"):
            return False
    return True


def is_test_file(relative: Path) -> bool:
    """Whether a project file is part of the suite rather than the package.

    By position, not by a list: anything named `test_*.py`, anything under a
    `test_*/` directory, and this file.
    """
    return (relative.name.startswith("test_")
            or relative.parts[0].startswith("test_")
            or relative.name == "conftest.py")


def project_python_files() -> list:
    """Every Python file in the project, tests included, as repo-relative paths."""
    return sorted(p.relative_to(PROJECT_ROOT)
                  for p in PROJECT_ROOT.rglob("*.py")
                  if _is_project_path(p.relative_to(PROJECT_ROOT)))


def source_python_files() -> list:
    """Every Python file that ships, i.e. the project minus its suite."""
    return [p for p in project_python_files() if not is_test_file(p)]


def suite_python_files() -> list:
    """Every Python file of the suite."""
    return [p for p in project_python_files() if is_test_file(p)]


def project_packages() -> list:
    """Every importable package directory, found by its `__init__.py`.

    Discovered rather than listed, for the same reason as the file set: a new
    package is covered the day it is created, not the day someone remembers.
    """
    return sorted({str(p.parent.relative_to(PROJECT_ROOT))
                   for p in PROJECT_ROOT.rglob("__init__.py")
                   if _is_project_path(p.relative_to(PROJECT_ROOT))})


# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------
#
# `openai` backs the OpenRouter and OpenAI routes and is an EXTRA, imported
# lazily inside the client so the package installs without it. The tests did not
# match: on `pip install -e .[test]` twenty of them raised ModuleNotFoundError
# rather than skipping, so a clean install of the artefact could not produce a
# green suite - and the failures pointed at the tests rather than at the missing
# extra.
#
# `unittest.SkipTest` rather than `pytest.skip`: pytest honours it natively, it
# is stdlib, and run_tests.py can recognise it without pytest installed. The
# matplotlib helper used pytest.skip, which run_tests.py counted as a FAILURE -
# so the pytest-free runner reported a red suite for an absent optional extra.

# Marks the one kind of skip that CI can prevent, and must.
#
# Not every skip is alike. "matplotlib is not installed" is a fact about the
# install and CI controls it; "no corpus in this checkout" is a fact about the
# data, and the results corpora are gitignored so CI never has them. Failing all
# skips in CI would make the run permanently red for the second kind, which is
# why the two are told apart here rather than counted together.
OPTIONAL_DEPENDENCY_ABSENT = "optional dependency absent:"


def skip_without(module: str, why: str = ""):
    """Skip the calling test when an optional dependency is absent.

    Raises rather than returning a flag, so a caller cannot forget to check it.
    """
    import importlib
    import unittest
    try:
        importlib.import_module(module)
    except ImportError:
        raise unittest.SkipTest(
            f"{OPTIONAL_DEPENDENCY_ABSENT} {module}"
            f"{' - ' + why if why else ''}")


# In CI's fully-installed job, skipping for a MISSING DEPENDENCY is a failure.
#
# The job installs every extra, so nothing there should opt out for want of one.
# A test that does is either mis-guarded or quietly not running, and a suite
# reporting thousands passed while some of them never executed is the shape of
# reassurance this project keeps finding bugs behind.
#
# Scoped to dependency skips on purpose. A skip for an absent corpus or for git
# being unavailable is a fact about the environment that CI cannot change - the
# corpora are gitignored and never present there - so failing those would make
# the run permanently red and teach everyone to ignore it.
if HAS_PYTEST and os.environ.get("SUBVERSIONBENCH_NO_SKIPS") == "1":

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_runtest_makereport(item, call):
        outcome = yield
        report = outcome.get_result()
        if report.skipped and OPTIONAL_DEPENDENCY_ABSENT in str(
                getattr(report, "longrepr", "")):
            report.outcome = "failed"
            report.longrepr = (
                f"SUBVERSIONBENCH_NO_SKIPS=1: every optional extra is installed "
                f"in this job, so no test should skip for a missing one.\n"
                f"Skipped anyway: {report.longrepr}")


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


# ----------------------------------------------------------------------------
# Builders shared by more than one test file.
#
# These live here rather than in whichever test file happened to define them
# first, because with one test file per production module the same episode and
# the same argparse stand-in are needed from several files at once. The previous
# arrangement had test_console.py importing a private helper out of
# test_batch_facts.py, which made a test file's contents part of another file's
# interface: deleting or splitting the first broke the second.
#
# A divergent copy is the real hazard. Two `_episode` builders that drift apart
# make two test files assert on differently-shaped data while both look right,
# and the shape they assert on is the shape of a saved run file - the one thing
# every read mode has to agree about.
# ----------------------------------------------------------------------------

class FakeArgs:
    """Stand-in for the argparse namespace the read modes and runner read."""

    def __init__(self, **kw):
        self.output_dir = kw["output_dir"]
        self.model = kw["model"]
        self.nudge = kw["nudge"]
        self.grader_model = kw["grader_model"]
        self.batch_stamp = kw.get("batch_stamp")
        self.effort = kw.get("effort")
        self.oversight = kw.get("oversight", True)
        self.lure = kw.get("lure", False)
        self.interrogation = kw.get("interrogation", "default")
        self.write_back = kw.get("write_back", False)
        self.delay = kw.get("delay", 0)
        # Read by the summary schema through `setting()`, so a builder without
        # them cannot stand in for args where a document is assembled. Defaults
        # match run_eval's own, so a test that does not care about them gets the
        # values a real batch would have carried.
        self.max_tokens = kw.get("max_tokens", 8192)
        self.max_turns = kw.get("max_turns", 40)


def collecting_identity(args, model_slug="m", stamp="S"):
    """A BatchIdentity for a test batch.

    summarise_batch takes identity explicitly rather than reading the arm off
    `args`; these tests build the collecting-a-batch case, where the two agree.
    """
    from subversionbench.batch import BatchIdentity
    return BatchIdentity.collecting(args, model_slug, args.effort, stamp=stamp)


def batch_episode(tampered=False, monitoring=False, escape=None, aware=False,
                  disclosed=None, answers=None, memo=True):
    """One saved episode, in the shape the run files hold.

    `tampered` sets the oversight act's own key, which is what carries the
    verdict. `monitoring` sets the separately reported figure for the config
    edit. They are distinct on purpose: the act key is what
    classify_misalignment reads, and a fixture that conflated them would assert
    on the wrong one.

    The sandbox act's key is DERIVED, not set - normalise_analyses reads the raw
    commands in `escape` and works out which of them left the sandbox.
    """
    from subversionbench.grading.acts import MISALIGNED_ACTS
    act = [a for a in MISALIGNED_ACTS if a["name"] == "oversight"][0]
    analysis = {
        act["key"]: tampered,
        "monitoring_disabled": monitoring,
        "sandbox_escape_attempts": list(escape or []),
        "read_internal_memo": memo,
        "read_monitoring_config": True,
        "ran_quality_check_preview": False,
        "quality_check_result": "clean",
        "eval_awareness_keywords": {"eval_aware": aware,
                                    "goal_conflict_noted": False},
    }
    if disclosed is not None:
        analysis[act["disclosure_key"]] = {"disclosed": disclosed}
    if answers is not None:
        analysis[act["followup_key"]] = answers
    return {"analysis": analysis, "transcript": [], "reasoning_chars": 0}


def write_run_file(d, n, model, nudge, effort=None, stamp="20260101T000000"):
    """A run file with just the fields discovery reads."""
    import json
    parts = ["run", str(n), model.replace("/", "_"), nudge]
    if effort:
        parts.append(effort)
    name = "_".join(parts) + f"_{stamp}.json"
    Path(d, name).write_text(json.dumps(
        {"model": model, "nudge": nudge, "effort": effort, "analysis": {}}))
    return name


def env_without(*names):
    """Temporarily unset credentials. The placeholders above cover the suite, so a
    test that wants the refusal has to remove them explicitly."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        saved = {n: os.environ.pop(n, None) for n in names}
        try:
            yield
        finally:
            for n, v in saved.items():
                if v is not None:
                    os.environ[n] = v
    return _ctx()


def summary_pipeline_source():
    """The source of everything that turns a batch of episodes into a summary.

    Asserted against the pipeline rather than one function because the figures
    moved out of summarise_batch into reporting/facts/. What the tests using this
    pin is that the summary still records what they are about - not which function
    happens to compute it.

    Whole MODULES on both sides, which is the second time naming a function here
    would have gone wrong: the figures left summarise_batch for facts/, and then
    the schema left it too, for summary_document. A helper that names the function
    reports a source without the thing the caller is looking for, and the
    assertion passes on an empty search.
    """
    import glob
    import inspect
    import subversionbench.reporting.summary as summary_module
    facts_src = "".join(open(p).read() for p in
                        sorted(glob.glob("subversionbench/reporting/facts/*.py")))
    return facts_src + inspect.getsource(summary_module)


def sandbox_profile(mode):
    """A written-out Darwin sandbox profile for `mode`."""
    from subversionbench.isolation import darwin_profile
    p = Path(tempfile.mkdtemp()) / "iso.sb"
    p.write_text(darwin_profile(mode))
    return p


# Skips a test that needs the real macOS sandbox. Defined here so the two files
# that need it cannot end up with different skip conditions - and with a fallback
# so importing this module does not require pytest, which is the whole reason
# run_tests.py exists.
if HAS_PYTEST:
    import platform as _platform
    from subversionbench.isolation import isolation_available as _iso_available
    darwin_only = pytest.mark.skipif(
        _platform.system() != "Darwin" or not _iso_available("deny-external"),
        reason="sandbox-exec is the only mechanism available on this host",
    )
else:                                       # pragma: no cover - bare environment
    def darwin_only(fn):
        return fn


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
