"""
The CI workflow against what the project actually promises.

A workflow file is configuration nobody reads once it is green, so the things
that would quietly stop being true are checked here instead:

  - the Python floor. pyproject declares `requires-python >= 3.10` and nothing
    verified it; if the matrix drops 3.10 while the declaration stays, the
    project claims support for a version it never runs.
  - the fully-installed job must install every extra and forbid dependency
    skips, because that job's whole purpose is that nothing opts out there.
  - the minimal job must NOT install the extras, because its purpose is the
    opposite: proving the optional dependencies really are optional. Twenty
    tests used to raise ModuleNotFoundError on a clean `.[test]` install.
  - no job may want a credential. Nothing in the suite reaches a model, and a
    workflow that asked for a key would be the first place one could leak.

Parsed rather than grepped, so a restructuring of the file cannot make a check
pass by accident. Skipped when PyYAML is absent, since it is not a dependency of
this project - the checks below are about CI's own configuration.
"""

import re
from pathlib import Path

WORKFLOW = Path(__file__).parent / ".github" / "workflows" / "tests.yml"


def _workflow() -> dict:
    from conftest import skip_without
    skip_without("yaml", "PyYAML parses the workflow for these checks")
    import yaml
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _declared_floor() -> tuple:
    """The (major, minor) in `requires-python` from pyproject."""
    body = Path(__file__).parent.joinpath("pyproject.toml").read_text(
        encoding="utf-8")
    m = re.search(r'requires-python\s*=\s*"[^0-9]*(\d+)\.(\d+)"', body)
    assert m, "pyproject does not declare requires-python"
    return int(m.group(1)), int(m.group(2))


def _declared_extras() -> set:
    """The names under `[project.optional-dependencies]`.

    By regex, like `test_dependencies._declared_requirements`, rather than with
    `tomllib`: that is stdlib only from 3.11, and 3.10 is the floor this project
    promises and the version CI runs first. Importing it failed the 3.10 job
    outright, and made the declared-dependency guard report `tomllib` as an
    undeclared third-party package, since it builds its stdlib set from the
    running interpreter.
    """
    body = Path(__file__).parent.joinpath("pyproject.toml").read_text(
        encoding="utf-8")
    section = body.split("[project.optional-dependencies]")[1].split("\n[")[0]
    return set(re.findall(r"^([A-Za-z0-9_-]+)\s*=\s*\[", section, re.M))


def _steps_text(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


class TestTheWorkflowExistsAndParses:
    def test_the_file_is_there(self):
        assert WORKFLOW.is_file(), (
            "the suite runs only when someone remembers without this file")

    def test_it_parses(self):
        assert set(_workflow()["jobs"]) >= {"suite", "minimal-install"}

    def test_it_runs_on_push_and_pull_request(self):
        # `on` is the YAML 1.1 boolean True, which is why it is looked up both
        # ways rather than assumed.
        workflow = _workflow()
        triggers = workflow.get("on", workflow.get(True))
        assert {"push", "pull_request"} <= set(triggers)


class TestTheMatrixMatchesWhatThePackagePromises:
    def test_the_declared_floor_is_actually_tested(self):
        """requires-python is a promise. Nothing else checks it."""
        major, minor = _declared_floor()
        floor = f"{major}.{minor}"
        versions = _workflow()["jobs"]["suite"]["strategy"]["matrix"]["python"]
        assert floor in [str(v) for v in versions], (
            f"pyproject promises Python >= {floor} but CI never runs it; "
            f"the matrix is {versions}")

    def test_more_than_one_version_is_tested(self):
        """One version is a single machine with extra steps."""
        versions = _workflow()["jobs"]["suite"]["strategy"]["matrix"]["python"]
        assert len(versions) >= 2, versions

    def test_a_failing_version_does_not_hide_the_others(self):
        assert _workflow()["jobs"]["suite"]["strategy"]["fail-fast"] is False


class TestTheTwoJobsTestOppositeThings:
    def test_the_suite_job_installs_every_extra(self):
        extras = _declared_extras()
        assert extras, "pyproject declares no optional-dependencies"
        run = _steps_text(_workflow()["jobs"]["suite"])
        install = re.search(r"pip install -e \"\.\[([^\]]+)\]\"", run)
        assert install, f"no editable install with extras found in:\n{run}"
        named = {e.strip() for e in install.group(1).split(",")}
        # `openai` and `openrouter` declare the same package, so either covers
        # it; every other extra must be named.
        missing = {e for e in extras if e not in named}
        assert missing <= {"openai"}, (
            f"the fully-installed job does not install {sorted(missing)}, so a "
            f"test needing it would skip in the one job that forbids skipping")

    def test_the_suite_job_forbids_dependency_skips(self):
        steps = _workflow()["jobs"]["suite"]["steps"]
        env = {k: v for step in steps for k, v in (step.get("env") or {}).items()}
        assert env.get("SUBVERSIONBENCH_NO_SKIPS") == "1", (
            "without this a mis-guarded test can skip in CI unnoticed")

    def test_the_minimal_job_does_not_install_the_extras(self):
        """Its purpose is the opposite of the suite job's. Installing charts or
        openai here would make it a duplicate and stop it proving anything."""
        run = _steps_text(_workflow()["jobs"]["minimal-install"])
        install = re.search(r"pip install -e \"\.\[([^\]]+)\]\"", run)
        assert install, run
        named = {e.strip() for e in install.group(1).split(",")}
        assert named == {"test"}, named

    def test_the_minimal_job_checks_the_extras_are_really_absent(self):
        """Otherwise a transitive dependency could install one and the job would
        silently become a second copy of the suite job."""
        run = _steps_text(_workflow()["jobs"]["minimal-install"])
        assert "find_spec" in run and "matplotlib" in run and "openai" in run


class TestNoJobWantsACredential:
    def test_no_secret_is_referenced(self):
        body = WORKFLOW.read_text(encoding="utf-8")
        # `secrets.GITHUB_TOKEN` is issued by Actions itself and is not a model
        # credential, so it is the one permitted mention.
        offenders = [m for m in re.findall(r"secrets\.[A-Z_]+", body)
                     if m != "secrets.GITHUB_TOKEN"]
        assert not offenders, offenders

    def test_no_api_key_is_named(self):
        body = WORKFLOW.read_text(encoding="utf-8").upper()
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                     "OPENROUTER_API_KEY"):
            assert name not in body, (
                f"{name} must not appear in CI: nothing in the suite reaches a "
                f"model, and a workflow that asks for a key is where one leaks")

    def test_the_workflow_only_needs_read_access(self):
        assert _workflow()["permissions"] == {"contents": "read"}
