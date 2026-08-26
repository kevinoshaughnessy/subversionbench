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
