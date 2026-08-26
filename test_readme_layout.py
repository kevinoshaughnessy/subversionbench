"""
The layout document against the files that actually exist, and the README's
links against the things they point at.

Nothing kept the two in step, and they drifted by eight entries: isolation.py,
rollout.py, scenario.py, two grading detectors and four repo-root scripts were all
absent from a section whose only job is to say what is where. One of them,
scenario_tool.py, is the command the scenario docs tell a reader to run.

A layout that is merely mostly right is worse than none, because a reader who finds
one module missing cannot tell whether the next absence means "not listed" or "does
not exist". So this is checked rather than maintained by hand.

WHERE THE LISTING LIVES
-----------------------
`docs/Layout.md`. It was a 136-line block in the README, which put a reference
table in the middle of the page someone reads to get started; the README now
carries a condensed version and links onward. The checks follow the listing
rather than the file it used to be in - and one of them asserts the README still
links to it, because a condensed overview whose pointer has rotted is worse than
the long section it replaced.
"""

import glob
import os
import re

LAYOUT_DOC = "docs/Layout.md"

# Deliberately not listed, with the reason. Anything else must appear.
NOT_LISTED = {
    "conftest.py": "pytest plumbing, like the test_*.py files themselves",
}


def _layout_block() -> str:
    body = open(LAYOUT_DOC, encoding="utf-8").read()
    assert "```" in body, f"{LAYOUT_DOC} has no fenced listing"
    return body.split("```")[1]


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
            f"these modules are not in {LAYOUT_DOC}: {missing}")

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
            f"these root scripts are not in {LAYOUT_DOC}: {missing}. "
            f"Add them, or add them to NOT_LISTED with a reason.")


class TestTheReadmeStillPointsAtTheFullListing:
    """The condensed overview is only an improvement while the link works.

    A reader who cannot find the full listing is worse off than one who had to
    scroll past it, so the pointer is checked as strictly as the listing.
    """

    def test_the_layout_document_exists(self):
        assert os.path.exists(LAYOUT_DOC)

    def test_the_readme_links_to_it(self):
        body = open("README.md", encoding="utf-8").read()
        targets = [t for _, t in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', body)]
        assert LAYOUT_DOC in targets, (
            f"the README no longer links to {LAYOUT_DOC}, so the full listing "
            f"is unreachable from the page a reader starts on")

    def test_the_readme_link_sits_in_the_layout_section(self):
        """Not merely somewhere on the page: in the section whose job it is."""
        body = open("README.md", encoding="utf-8").read()
        assert "## Layout" in body, "the README has no Layout section"
        section = body.split("## Layout")[1].split("\n## ")[0]
        assert LAYOUT_DOC in section, (
            f"the README's Layout section does not link to {LAYOUT_DOC}")

    def test_the_readme_no_longer_carries_the_whole_listing(self):
        """The point of the move. If the full block comes back, this file is
        checking one copy while readers read another."""
        body = open("README.md", encoding="utf-8").read()
        section = body.split("## Layout")[1].split("\n## ")[0]
        listed_in_readme = set(re.findall(r'([\w./-]+\.(?:py|sh))', section))
        assert len(listed_in_readme) <= 12, (
            f"the README's Layout section names {len(listed_in_readme)} files "
            f"again; the full listing belongs in {LAYOUT_DOC}")

    def test_the_documentation_index_counts_its_companions_correctly(self):
        """The index says how many companion documents there are, in words. It
        said "five" while listing five; adding one makes that sentence wrong,
        and a wrong count is the kind of thing nobody notices for months."""
        body = open("README.md", encoding="utf-8").read()
        index = body.split("## Documentation")[1].split("\n## ")[0]
        linked = {t for _, t in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', index)
                  if t.startswith("docs/")}
        words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                 7: "seven", 8: "eight", 9: "nine"}
        expected = words.get(len(linked))
        assert expected and f"{expected} companion" in index, (
            f"the Documentation index links {len(linked)} docs/ files but does "
            f"not say \"{expected} companions\"")


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
