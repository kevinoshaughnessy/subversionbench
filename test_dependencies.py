"""
Dependency floors, and the lock file that reproduces a published stack.

`pyproject` declares minimums and `requirements.lock` pins exact versions. The two
answer different questions - what will install, and what produced these results - and
both are checked here so neither drifts from the code that relies on it.

The minimums below are set by published advisories rather than by the oldest version
that happens to work. They are hardcoded on purpose: a test must not reach the network
to decide whether it passes, and a fix version does not change once published.
"""

import re
from pathlib import Path

# package -> (minimum, why). Raising a floor is fine; lowering one past these needs a
# reason better than "it seemed to work".
ADVISORY_FLOORS = {
    "anthropic": ("0.87.0",
                  "GHSA-q5f5-3gjm-7mfm (memory-tool files created 0o666) and "
                  "GHSA-w828-4qhx-vxx3 (memory-tool path validation TOCTOU, "
                  "sandbox escape); both fixed in 0.87.0"),
    "pytest": ("9.0.3",
               "GHSA-6w46-j5rx-g56g (predictable /tmp/pytest-of-{user}, local DoS "
               "or privilege gain); fixed in 9.0.3"),
}


def _version_tuple(text):
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def _declared_requirements():
    """Every requirement string in pyproject, from `dependencies` and every extra."""
    body = Path("pyproject.toml").read_text()
    found = []
    for block in re.findall(r"(?:dependencies|\w+)\s*=\s*\[(.*?)\]", body, re.S):
        found += re.findall(r'"([^"]+)"', block)
    return found


class TestTheFloorsClearTheAdvisories:
    def test_no_declared_minimum_admits_a_vulnerable_version(self):
        declared = _declared_requirements()
        for package, (floor, why) in ADVISORY_FLOORS.items():
            matches = [r for r in declared if r.split(">=")[0].strip() == package]
            assert matches, f"{package} is no longer declared in pyproject"
            for requirement in matches:
                assert ">=" in requirement, (
                    f"{requirement!r} has no minimum, so it admits any version. "
                    f"{why}")
                declared_min = requirement.split(">=", 1)[1]
                assert _version_tuple(declared_min) >= _version_tuple(floor), (
                    f"{package}>={declared_min} admits a version with a published "
                    f"advisory. {why}")

    def test_the_reason_is_recorded_beside_each_floor(self):
        """A bare version number invites someone to relax it. The advisory ID is what
        makes the constraint arguable rather than arbitrary."""
        body = Path("pyproject.toml").read_text()
        for package, (_, why) in ADVISORY_FLOORS.items():
            advisories = re.findall(r"GHSA-[\w-]+", why)
            assert advisories, f"no advisory recorded for {package}"
            assert any(a in body for a in advisories), (
                f"pyproject does not say why {package}'s floor is where it is")


class TestEveryImportedPackageIsDeclared:
    def test_nothing_is_used_undeclared(self):
        """pyflakes was imported by the test suite and declared nowhere, so a clean
        install skipped the undefined-name guard silently - the guard that caught
        three bad import prunings during the refactor."""
        import ast
        import glob
        import sys

        stdlib = set(sys.stdlib_module_names)
        local = {"conftest"}
        imported = set()
        for path in (glob.glob("subversionbench/**/*.py", recursive=True)
                     + glob.glob("trends/*.py")
                     + glob.glob("report/*.py")
                     + glob.glob("*.py") + glob.glob("test_*/*.py")):
            for node in ast.walk(ast.parse(Path(path).read_text())):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
        # A local package is local whether it is a directory or a single file.
        # `subversionbench` and `conftest` used to be named here one at a time,
        # which made splitting `trends/` out of a root script look like an
        # undeclared third-party dependency.
        third_party = {m for m in imported
                       if m not in stdlib and m not in local
                       and not m.startswith("test_")
                       and not Path(f"{m}.py").exists()
                       and not Path(m, "__init__.py").exists()}
        declared = {r.split(">=")[0].split("[")[0].strip().lower()
                    for r in _declared_requirements()}
        missing = sorted(m for m in third_party if m.lower() not in declared)
        assert not missing, (
            f"imported but not declared in pyproject: {missing}. An undeclared "
            f"dependency makes a clean install behave differently from yours.")


class TestTheLockFileMatchesWhatIsInstalled:
    def _pins(self):
        text = Path("requirements.lock").read_text()
        return dict(line.split("==", 1)
                    for line in text.splitlines()
                    if "==" in line and not line.startswith("#"))

    def test_it_exists_and_pins_exactly(self):
        pins = self._pins()
        assert pins, "requirements.lock has no pins"
        for package, version in pins.items():
            assert re.fullmatch(r"[\w.!+-]+", version), (package, version)

    def test_it_does_not_pin_the_project_itself(self):
        """The project is not a dependency of itself, and its editable version would
        go stale in the lock the moment pyproject moved."""
        assert "subversionbench" not in {k.lower() for k in self._pins()}

    def test_the_locked_versions_clear_the_advisory_floors(self):
        pins = {k.lower(): v for k, v in self._pins().items()}
        for package, (floor, why) in ADVISORY_FLOORS.items():
            if package in pins:
                assert _version_tuple(pins[package]) >= _version_tuple(floor), (
                    f"the lock pins {package}=={pins[package]}, below the floor. "
                    f"{why}")

    def test_the_direct_dependencies_are_all_locked(self):
        """A lock that omits the SDK cannot reproduce a rollout: TOOLS is hashed into
        the fingerprint and blocks.py normalises the SDK's own response shapes."""
        pins = {k.lower() for k in self._pins()}
        for package in ("anthropic", "openai", "pytest", "pyflakes"):
            assert package in pins, f"{package} is not pinned in requirements.lock"


class TestTheInstalledMetadataIsNotStale:
    def test_the_installed_version_matches_pyproject(self):
        """`pip install -e .` records a version at install time. Left stale it
        misreports which code produced a result - the metadata said 0.9.0 while
        pyproject said 42.0.0."""
        from importlib.metadata import version
        declared = re.search(r'^version = "([^"]+)"',
                             Path("pyproject.toml").read_text(), re.M).group(1)
        assert version("subversionbench") == declared, (
            "re-run `pip install -e . --no-deps` to refresh the install metadata")


class TestBothTestRunnersCanRunEverything:
    """README documents `python run_tests.py` as a pytest-free equivalent.

    A pytest-only decorator does not fail loudly there - it makes the standalone
    runner report a failure it cannot explain, which is how one slipped in.
    """

    def test_no_test_uses_a_pytest_only_decorator(self):
        # Matched as a decorator LINE, not as a substring: this file names the
        # markers in order to look for them, and a substring search would find
        # its own strings and never be able to pass.
        import glob
        markers = ("@pytest.mark.parametrize", "@pytest.fixture",
                   "@pytest.mark.usefixtures")
        offenders = []
        for path in sorted(glob.glob("test_*.py") + glob.glob("test_*/*.py")):
            for line in Path(path).read_text().splitlines():
                stripped = line.strip()
                for marker in markers:
                    if stripped.startswith(marker):
                        offenders.append(f"{path}: {marker}")
        assert not offenders, (
            "these only work under pytest, and run_tests.py cannot interpret them: "
            + ", ".join(offenders) + ". Use a loop, or a plain helper.")
