"""
The README's Layout section against the files that actually exist.

Nothing kept the two in step, and they drifted by eight entries: isolation.py,
rollout.py, scenario.py, two grading detectors and four repo-root scripts were all
absent from a section whose only job is to say what is where. One of them,
scenario_tool.py, is the command the scenario docs tell a reader to run.

A layout that is merely mostly right is worse than none, because a reader who finds
one module missing cannot tell whether the next absence means "not listed" or "does
not exist". So this is checked rather than maintained by hand.
"""

import glob
import os
import re

# Deliberately not listed, with the reason. Anything else must appear.
NOT_LISTED = {
    "conftest.py": "pytest plumbing, like the test_*.py files themselves",
}


def _layout_block() -> str:
    body = open("README.md").read()
    assert "## Layout" in body, "the README has no Layout section"
    return body.split("## Layout")[1].split("```")[1]


def _listed_files() -> set:
    return set(re.findall(r'([\w./-]+\.(?:py|sh))', _layout_block()))


# Every package in the repository, so the Layout is checked against all of them
# rather than against whichever one existed when this file was written. `trends/`
# and `report/` were both split out of root scripts and would otherwise have gone
# unlisted module by module - silently, which is the exact drift this file exists
# to catch.
#
# Which is what the tuple this used to hold could not do: it named the three that
# existed the day it was written, and a fourth package would have been unlisted
# and unnoticed. `conftest.project_packages()` finds them by their `__init__.py`.
def _packages() -> tuple:
    from conftest import project_packages
    return tuple(p for p in project_packages()
                 if "/" not in p and not p.startswith("test_"))


def _package_modules() -> list:
    from conftest import source_python_files
    packages = _packages()
    return sorted(str(p) for p in source_python_files()
                  if p.parts[0] in packages)


class TestEveryModuleIsListed:
    def test_no_package_module_is_missing(self):
        """__init__.py files are exempt: the Layout names the packages themselves,
        and both say in prose that their __init__ is the public API."""
        listed = _listed_files()
        missing = sorted(
            p for p in _package_modules()
            if os.path.basename(p) != "__init__.py"
            and os.path.basename(p) not in listed)
        assert not missing, (
            f"these modules are not in the README Layout: {missing}")

    def test_no_root_script_is_missing(self):
        """The scripts an operator invokes directly. scenario_tool.py went unlisted
        while the scenario documentation told readers to run it."""
        listed = _listed_files()
        missing = sorted(
            os.path.basename(p) for p in glob.glob("*.py") + glob.glob("*.sh")
            if not os.path.basename(p).startswith("test_")
            and os.path.basename(p) not in listed
            and os.path.basename(p) not in NOT_LISTED)
        assert not missing, (
            f"these root scripts are not in the README Layout: {missing}. "
            f"Add them, or add them to NOT_LISTED with a reason.")


class TestEveryEntryExists:
    def test_the_layout_names_nothing_that_has_been_deleted(self):
        """The other direction. A stale entry sends a reader looking for a file
        that was removed or renamed, which is the more confusing failure."""
        stale = []
        existing = {os.path.basename(p) for p in _package_modules()}
        for f in sorted(_listed_files()):
            if f not in existing and not glob.glob(f):
                stale.append(f)
        assert not stale, f"the Layout names files that do not exist: {stale}"

    def test_the_exemption_list_has_no_stale_entries(self):
        gone = [f for f in NOT_LISTED if not os.path.exists(f)]
        assert not gone, f"NOT_LISTED names files that no longer exist: {gone}"


class TestTheReadmeLinksResolve:
    def test_every_relative_link_points_at_something(self):
        """The Layout is not the only place the README claims a path."""
        body = open("README.md").read()
        broken = [target for _, target in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', body)
                  if not target.startswith(("http", "mailto", "#"))
                  and not os.path.exists(target.split("#")[0])]
        assert not broken, f"broken relative links in the README: {broken}"

    def test_every_anchor_names_a_heading_that_exists(self):
        """The other half of a `file.md#section` link, and the half that rots
        silently: the path check above passes on any anchor at all, and a stale
        one just drops the reader at the top of a long document with no sign
        that it went wrong. Six README links carry an anchor.
        """
        def slugs(path):
            out = set()
            for line in open(path):
                if line.startswith("#"):
                    title = line.lstrip("#").strip()
                    out.add(re.sub(r"[^\w\- ]", "", title).lower().replace(" ", "-"))
            return out

        body = open("README.md").read()
        stale = []
        for _, target in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', body):
            if target.startswith(("http", "mailto", "#")) or "#" not in target:
                continue
            path, anchor = target.split("#", 1)
            if os.path.exists(path) and anchor not in slugs(path):
                stale.append(target)
        assert not stale, (
            f"these README links name a heading that does not exist, so they "
            f"land at the top of the file instead: {stale}")
