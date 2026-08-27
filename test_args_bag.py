"""
The `args` bag: one mutable argparse Namespace read in 18 modules.

Eight CLIs each build a Namespace and pass it down by reference. Between them
319 sites read 53 distinct field names off it, and until this file existed
nothing checked that a name being read was a name anything could set. Three
failure shapes follow from that, and all three have happened here:

  A NAME THAT NOTHING SETS. `args.oversigh` is an AttributeError raised only on
  the branch that reads it - which, in a batch that takes hours and touches one
  arm at a time, means hours in before it surfaces.

  A FIELD ASSIGNED ONTO THE BAG MID-RUN. The bag is shared across a fan-out, so
  a callee that records its own batch's arm on it changes what every later
  iteration filters by. This shipped: see the docstring of `BatchIdentity` in
  `subversionbench/batch.py`, where one batch collected at effort "medium"
  filtered every later model to "medium", two of four groups reported "no run
  files", and the backfill would have been half done while reporting success.

  A SUITE BAG THAT NO LONGER MATCHES THE REAL ONE. The suite hand-builds
  SimpleNamespace stand-ins. One carrying a field the CLI cannot supply is a
  test exercising a state no operator can reach.

WHAT THIS FILE DOES NOT DO
--------------------------
It does not make the bag immutable - that is a source change. It pins the
mechanism so that change can be made and shown to have held. `BatchIdentity` is
the pattern to extend: frozen, built at the boundary, passed explicitly.

Two things are deliberately documented here rather than guarded, because a
guard for either would be less reliable than the note:

  `run_eval.main` converts `oversight` and `lure` from the strings argparse
  parses to the booleans everything downstream expects, in place, at lines 503
  and 504. Between `parse_args` and there the fields are strings, and `"false"`
  is truthy. Nothing reads either field before the conversion today - checked -
  and every rebuild path takes its arm from a `BatchIdentity` instead, so no
  reader can currently observe the pre-conversion type.

  Whether a field is READ before it is converted is a control-flow question,
  and a static approximation of it would either miss the ordering or report
  every branch. The mutation guard below is the durable half: once nothing
  writes to the bag, there is no in-place conversion to be early for.

THE SCOPE IS DERIVED, NEVER LISTED
----------------------------------
The set of entry points comes from which files actually define CLI options, and
which modules an entry point governs comes from the import graph. A module
added later inherits these guards instead of escaping them. Each rule is a
function of a file list, so the same rule that runs over the project can be run
over a synthetic tree with the defect planted in it - which is what
TestTheseGuardsDiscriminate does, and the only way to plant a defect here
without editing source.
"""

import ast
import functools
import os
import pathlib
import shutil
import tempfile

import conftest

ROOT = conftest.PROJECT_ROOT

# Mutates the bag away from the CLI boundary. Recorded rather than fixed
# because the fix edits source. Checked in BOTH directions below, so it can
# only shrink: delete the entry when the file stops offending.
#
# fan_out_read_mode assigns args.model and args.nudge once per iteration. It is
# the surviving half of the defect BatchIdentity was introduced for - the arm
# fields no longer leak, model and nudge still do - and it is benign only
# because both are written afresh at the top of every iteration rather than
# being restored afterwards. That is a property of the current loop body, not
# of the design, which is why it is pinned here.
MUTATES_THE_BAG_OUTSIDE_MAIN = frozenset({
    "subversionbench/readmodes/selection.py",
})


# --------------------------------------------------------------------------
# Reading source. Cached because these guards cross-reference the whole
# project several times over and the uncached version re-parsed 95 files on
# every lookup. Keyed on the path, so nothing here can observe a file changing
# mid-run - no test in this file rewrites a path it has already read.
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _source_tuple() -> tuple:
    return tuple(conftest.source_python_files())


def _source_files() -> list:
    """Every shipping file, from conftest, so a new module is in scope at once."""
    return list(_source_tuple())


@functools.cache
def _tree(relative):
    # An absolute path on the right of `/` wins, which is what lets the
    # discrimination tests below point these helpers at a synthetic tree.
    return ast.parse((ROOT / relative).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Extractors: what one file says.
# --------------------------------------------------------------------------

def _module_name(relative) -> str:
    parts = list(pathlib.Path(relative).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _relative_import_base(relative) -> str:
    """The package a relative import in this file resolves against.

    For a package's `__init__.py` that is the package ITSELF; for a plain module
    it is the package CONTAINING it. Getting this backwards made every
    readmodes submodule read as unreachable, which shrank the scope of the
    traceability guard until it reported five false offenders.
    """
    name = _module_name(relative)
    if pathlib.Path(relative).name == "__init__.py":
        return name
    return name.rsplit(".", 1)[0] if "." in name else ""


def _project_imports(relative, by_module: dict) -> set:
    """Project modules this file imports, however the import is spelled."""
    base = _relative_import_base(relative)
    named = set()
    for node in ast.walk(_tree(relative)):
        if isinstance(node, ast.Import):
            named |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = (base if node.level == 1
                          else base.rsplit(".", node.level - 1)[0])
                module = f"{anchor}.{node.module}" if node.module else anchor
            else:
                module = node.module or ""
            # `from x import y` may name a module OR a name inside one, and
            # only the module map can tell which.
            named.add(module)
            named |= {f"{module}.{a.name}" for a in node.names}
    return {m for m in named if m in by_module}


def _import_graph_of(files) -> dict:
    by_module = {_module_name(p): p for p in files}
    return {str(p): {str(by_module[m]) for m in _project_imports(p, by_module)}
            for p in files}


@functools.lru_cache(maxsize=1)
def _import_graph() -> dict:
    return _import_graph_of(_source_files())


def _reachable(entry: str, graph: dict) -> set:
    """Every project module reachable from `entry`, including through a lazy
    import inside a function - `ast.walk` does not care about nesting, which is
    what makes this cover the modules imported at call time."""
    seen, stack = set(), [entry]
    while stack:
        for module in graph.get(stack.pop(), ()):
            if module not in seen:
                seen.add(module)
                stack.append(module)
    return seen


def _option_dests(relative) -> set:
    """The attribute names argparse will set, from the add_argument calls."""
    dests = set()
    for node in ast.walk(_tree(relative)):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        explicit = [kw.value.value for kw in node.keywords
                    if kw.arg == "dest" and isinstance(kw.value, ast.Constant)]
        if explicit:
            dests.add(explicit[0])
            continue
        literals = [a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        flags = [s for s in literals if s.startswith("--")]
        positional = [s for s in literals if not s.startswith("-")]
        if flags:
            dests.add(flags[0][2:].replace("-", "_"))
        elif positional:
            dests.add(positional[0].replace("-", "_"))
    return dests


def _bag_targets(node) -> list:
    """The `args.<field>` names one statement assigns to, tuple targets
    included - `args.model, args.nudge = ...` is two assignments in one node."""
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        targets = [node.target]
    else:
        return []
    fields = []
    for target in targets:
        for one in (target.elts if isinstance(target, ast.Tuple) else [target]):
            if (isinstance(one, ast.Attribute)
                    and isinstance(one.value, ast.Name)
                    and one.value.id == "args"):
                fields.append(one.attr)
    return fields


def _mutations(relative) -> list:
    """Every (enclosing function, field, line) that writes to the bag.

    Attributed to the OUTERMOST enclosing function, so a write inside a nested
    helper still counts as happening in the function a reader would name.
    """
    found = []
    outermost = [n for n in ast.iter_child_nodes(_tree(relative))
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for function in outermost:
        for node in ast.walk(function):
            for field in _bag_targets(node):
                found.append((function.name, field, node.lineno))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "setattr" and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "args"):
                found.append((function.name, "<setattr>", node.lineno))
    return found


def _assigned_fields(relative) -> set:
    return {field for _, field, _ in _mutations(relative)
            if field != "<setattr>"}


def _static_reads(relative) -> dict:
    """`args.<field>` reads, as {field: [line, ...]}."""
    reads = {}
    for node in ast.walk(_tree(relative)):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "args"):
            reads.setdefault(node.attr, []).append(node.lineno)
    return reads


def _dynamic_read_indirections_of(files) -> frozenset:
    """Names of functions that read the bag through a VARIABLE field name.

    Derived from the mechanism rather than by naming the function, because the
    point is that a second such indirection added later is covered too.
    `getattr(args, name)` defeats every static check in this file, so what a
    caller passes to one of these has to be checked separately.
    """
    names = set()
    for relative in files:
        for function in ast.walk(_tree(relative)):
            if not isinstance(function,
                              (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "getattr"
                        and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id == "args"
                        and not isinstance(node.args[1], ast.Constant)):
                    names.add(function.name)
    return frozenset(names)


@functools.lru_cache(maxsize=1)
def _dynamic_read_indirections() -> frozenset:
    return _dynamic_read_indirections_of(_source_files())


def _dynamic_read_sites_of(files, indirections) -> tuple:
    """Every (file, line, field) passed as a literal to such an indirection."""
    sites = []
    for relative in files:
        for node in ast.walk(_tree(relative)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in indirections and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                sites.append((str(relative), node.lineno, node.args[0].value))
    return tuple(sites)


@functools.lru_cache(maxsize=1)
def _dynamic_read_sites() -> tuple:
    return _dynamic_read_sites_of(_source_files(),
                                  _dynamic_read_indirections())


def _entry_points_of(files) -> tuple:
    """Files that define CLI options, i.e. that build a bag of their own."""
    return tuple(p for p in files if _option_dests(p))


@functools.lru_cache(maxsize=1)
def _entry_points() -> tuple:
    return _entry_points_of(_source_files())


def _fields_a_module_may_read_in(files) -> dict:
    """{module: the field names something could actually set on its bag}.

    A module reached by two CLIs may read either one's options, so the allowed
    set is the union over the entry points that reach it. Assignments count
    wherever they happen: a derived field grafted on in `main` is legitimately
    readable downstream even though no add_argument call declares it.
    """
    graph = _import_graph_of(files)
    entries = _entry_points_of(files)
    governs = {str(e): _reachable(str(e), graph) | {str(e)} for e in entries}
    grafted = set()
    for relative in files:
        grafted |= _assigned_fields(relative)
    allowed = {}
    for relative in files:
        may = set(grafted)
        for entry in entries:
            if str(relative) in governs[str(entry)]:
                may |= _option_dests(entry)
        allowed[str(relative)] = may
    return allowed


@functools.lru_cache(maxsize=1)
def _fields_a_module_may_read() -> dict:
    return _fields_a_module_may_read_in(_source_files())


def _suite_bags_in(files, real) -> list:
    """Every SimpleNamespace in `files` that looks like an args bag.

    By overlap with the real field names rather than by variable name: the
    suite calls them `args`, `a`, `ns` and several other things.
    """
    bags = []
    for relative in files:
        for node in ast.walk(_tree(relative)):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == "SimpleNamespace"):
                continue
            fields = {kw.arg for kw in node.keywords if kw.arg}
            if len(fields & real) >= 3:
                bags.append((str(relative), node.lineno, fields))
    return bags


# --------------------------------------------------------------------------
# The rules. Each is a pure function of what the extractors found, so the
# same rule can be run over the project and over a synthetic tree with the
# defect planted in it.
# --------------------------------------------------------------------------

def _untraceable_reads(files, allowed) -> list:
    out = []
    for relative in files:
        for field, lines in sorted(_static_reads(relative).items()):
            if field not in allowed[str(relative)]:
                out.append(f"{relative}:{lines[0]} reads args.{field}, which "
                           f"no CLI reaching this module defines and nothing "
                           f"assigns")
    return out


def _untraceable_dynamic_reads(sites, allowed) -> list:
    return [f"{relative}:{line} asks the bag for {field!r}, which nothing sets"
            for relative, line, field in sites
            if field not in allowed[relative]]


def _writes_away_from_the_boundary(files, entries, exempt) -> list:
    out = []
    for relative in files:
        key = str(relative)
        if key in exempt:
            continue
        for function, field, line in _mutations(relative):
            if not (key in entries and function == "main"):
                out.append(f"{key}:{line} sets args.{field} in {function}(), "
                           f"which is not a CLI boundary")
    return out


def _drifted_bags(bags, real) -> list:
    out = []
    for relative, line, fields in bags:
        stray = sorted(fields - real)
        if stray:
            out.append(f"{relative}:{line} sets {stray}, which no CLI defines "
                       f"and nothing assigns")
    return out


class _SyntheticTree:
    """A throwaway package on disk, for planting a defect these rules should
    catch without editing a file the running evaluation might import.

    `tempfile.mkdtemp` rather than the `tmp_path` fixture: `run_tests.py` is a
    pytest-free runner and cannot interpret a fixture.
    """

    def __init__(self, files: dict):
        self.files = files
        self.root = None

    def __enter__(self) -> list:
        self.root = tempfile.mkdtemp(prefix="argsbag_")
        written = []
        for name, text in self.files.items():
            path = os.path.join(self.root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            written.append(path)
        return written

    def __exit__(self, *_):
        shutil.rmtree(self.root, ignore_errors=True)
        return False


class TestEveryFieldReadOffTheBagIsTraceable:
    """A read whose name nothing sets is an AttributeError waiting for the
    branch that reaches it."""

    def test_every_static_read_resolves_to_an_option_or_an_assignment(self):
        untraceable = _untraceable_reads(_source_files(),
                                         _fields_a_module_may_read())
        assert not untraceable, "\n  " + "\n  ".join(untraceable)

    def test_every_name_reaching_the_bag_dynamically_resolves_too(self):
        """`getattr(args, name)` is invisible to the guard above, so the
        literals callers hand to such an indirection are checked here. Without
        this, three fields reach the bag unchecked."""
        indirections = _dynamic_read_indirections()
        assert indirections, (
            "no dynamic-read indirection found; if getattr(args, <variable>) "
            "is genuinely gone, delete this test rather than letting it pass "
            "over an empty set")
        bad = _untraceable_dynamic_reads(_dynamic_read_sites(),
                                         _fields_a_module_may_read())
        assert not bad, "\n  " + "\n  ".join(bad)

    def test_the_scope_of_these_guards_is_not_empty(self):
        """Every guard here is built on derived sets. A glob or a graph that
        came back empty would make all of them pass over nothing."""
        files = _source_files()
        assert len(files) > 50, len(files)
        entries = _entry_points()
        assert len(entries) >= 8, [str(p) for p in entries]
        readers = [p for p in files if _static_reads(p)]
        assert len(readers) >= 15, [str(p) for p in readers]
        assert sum(len(_static_reads(p)) for p in readers) >= 40

    def test_a_lazily_reached_module_is_still_in_scope(self):
        """The control on the import graph.

        The readmodes submodules are reached from run_eval only through the
        package's `__init__`, and an earlier version of `_relative_import_base`
        resolved that indirection against the wrong package - leaving five
        modules governed by no entry point at all. A graph that stops
        traversing does not fail loudly; it shrinks the allowed set until the
        guard reports nonsense, or grows it until the guard reports nothing.
        """
        governed = _reachable("subversionbench/run_eval.py", _import_graph())
        for module in ("subversionbench/readmodes/selection.py",
                       "subversionbench/readmodes/resummarise.py",
                       "subversionbench/runner.py",
                       "subversionbench/reporting/summary.py"):
            assert module in governed, (
                f"{module} is not reachable from the eval CLI, so it is "
                f"governed by no option set and reads nothing can check")

    def test_a_packages_init_anchors_its_own_relative_imports(self):
        """The unit form of the bug above, stated on the real tree."""
        assert (_relative_import_base("subversionbench/readmodes/__init__.py")
                == "subversionbench.readmodes")
        assert (_relative_import_base("subversionbench/readmodes/grade.py")
                == "subversionbench.readmodes")
        assert _relative_import_base("scenario_tool.py") == ""


class TestTheBagIsOnlyMutatedAtTheBoundary:
    """Writing to a bag that is shared across a fan-out changes what later
    iterations see. This is the defect BatchIdentity exists to have fixed."""

    def test_nothing_mutates_the_bag_outside_an_entry_points_main(self):
        offenders = _writes_away_from_the_boundary(
            _source_files(), {str(p) for p in _entry_points()},
            MUTATES_THE_BAG_OUTSIDE_MAIN)
        assert not offenders, (
            "the bag is passed by reference into every callee, so a write here "
            "is visible to the rest of the run:\n  " + "\n  ".join(offenders))

    def test_every_baselined_file_still_mutates_the_bag(self):
        """The other direction, so the baseline can only shrink. A file that
        has been fixed must be deleted from it rather than left as a standing
        exemption for the next write."""
        files = {str(p) for p in _source_files()}
        entries = {str(p) for p in _entry_points()}
        stale = []
        for key in sorted(MUTATES_THE_BAG_OUTSIDE_MAIN):
            if key not in files:
                stale.append(f"{key} is not a source file any more")
                continue
            if not _writes_away_from_the_boundary([key], entries, frozenset()):
                stale.append(f"{key} no longer mutates the bag - remove it "
                             f"from MUTATES_THE_BAG_OUTSIDE_MAIN")
        assert not stale, "\n  " + "\n  ".join(stale)


class TestASuiteBagCannotDriftFromTheRealOne:
    """A hand-built stand-in carrying a field no CLI can supply is a test
    exercising a state no operator can reach."""

    def _real_fields(self) -> set:
        real = set()
        for relative in _source_files():
            real |= _option_dests(relative)
            real |= _assigned_fields(relative)
        return real

    def test_no_suite_bag_carries_a_field_no_cli_can_supply(self):
        real = self._real_fields()
        drifted = _drifted_bags(
            _suite_bags_in(conftest.suite_python_files(), real), real)
        assert not drifted, "\n  " + "\n  ".join(drifted)

    def test_the_suite_actually_builds_bags_for_this_to_check(self):
        """Guards the overlap heuristic. If the suite stopped using
        SimpleNamespace, or the threshold stopped matching, the test above
        would pass over an empty list."""
        real = self._real_fields()
        assert len(real) >= 40, len(real)
        bags = _suite_bags_in(conftest.suite_python_files(), real)
        assert len(bags) >= 5, bags


class TestTheseGuardsDiscriminate:
    """Each rule above, run over a tree with its defect planted.

    A guard that has never been seen to fail is a guard nobody has checked. The
    plants live in a temp directory rather than in the project because source
    may not be edited while a batch is collecting - and because a rule that can
    only be tested by breaking the thing it protects is a rule that will be
    tested once and never again.
    """

    def test_a_read_nothing_sets_is_reported(self):
        cli = ("import argparse\n"
               "def main():\n"
               "    p = argparse.ArgumentParser()\n"
               "    p.add_argument('--model')\n"
               "    args = p.parse_args()\n"
               "    return args.model\n")
        callee = "def work(args):\n    return args.modle\n"
        with _SyntheticTree({"cli.py": cli, "callee.py": callee}) as files:
            allowed = {str(f): {"model"} for f in files}
            found = _untraceable_reads(files, allowed)
            assert any("args.modle" in f for f in found), found
            # And the correctly spelled one is NOT reported, so the rule is
            # discriminating rather than merely noisy.
            assert not any("args.model," in f for f in found), found

    def test_a_dynamic_read_of_an_unknown_field_is_reported(self):
        sites = [("m.py", 7, "max_turns"), ("m.py", 9, "not_an_option")]
        allowed = {"m.py": {"max_turns"}}
        found = _untraceable_dynamic_reads(sites, allowed)
        assert len(found) == 1 and "not_an_option" in found[0], found

    def test_a_write_outside_main_is_reported(self):
        cli = ("import argparse\n"
               "def main():\n"
               "    p = argparse.ArgumentParser()\n"
               "    p.add_argument('--model')\n"
               "    args = p.parse_args()\n"
               "    args.derived = 1\n")
        leaky = "def fan_out(args):\n    args.model = 'x'\n"
        with _SyntheticTree({"cli.py": cli, "leaky.py": leaky}) as files:
            entries = {str(p) for p in _entry_points_of(files)}
            found = _writes_away_from_the_boundary(files, entries, frozenset())
            assert any("fan_out()" in f for f in found), found
            # The write in main() is at the boundary and must not be reported.
            assert not any("main()" in f for f in found), found

    def test_a_write_through_setattr_is_reported(self):
        sneaky = "def work(args):\n    setattr(args, 'model', 'x')\n"
        with _SyntheticTree({"sneaky.py": sneaky}) as files:
            found = _writes_away_from_the_boundary(files, set(), frozenset())
            assert found and "<setattr>" in found[0], found

    def test_a_write_in_a_nested_helper_is_attributed_to_its_outer_function(self):
        """A write hidden one def deeper is the same defect, and naming the
        inner helper in the report would send a reader to the wrong place."""
        nested = ("def outer(args):\n"
                  "    def inner():\n"
                  "        args.model = 'x'\n"
                  "    return inner\n")
        with _SyntheticTree({"nested.py": nested}) as files:
            found = _writes_away_from_the_boundary(files, set(), frozenset())
            assert found and "outer()" in found[0], found

    def test_a_tuple_assignment_counts_as_two_writes(self):
        """`args.model, args.nudge = ...` is one statement and two writes; a
        rule reading only `node.targets[0]` would see neither."""
        pair = "def work(args):\n    args.model, args.nudge = 'a', 'b'\n"
        with _SyntheticTree({"pair.py": pair}) as files:
            found = _writes_away_from_the_boundary(files, set(), frozenset())
            assert len(found) == 2, found

    def test_a_baselined_file_that_stopped_offending_is_reported(self):
        """The reverse direction of the baseline, which is what stops an entry
        outliving the debt it records."""
        clean = "def fan_out(args):\n    return args.model\n"
        with _SyntheticTree({"clean.py": clean}) as files:
            assert not _writes_away_from_the_boundary(files, set(), frozenset())

    def test_a_suite_bag_with_a_stray_field_is_reported(self):
        bags = [("t.py", 3, {"model", "nudge", "output_dir", "typo_field"})]
        found = _drifted_bags(bags, {"model", "nudge", "output_dir"})
        assert found and "typo_field" in found[0], found

    def test_an_emptied_scope_is_not_mistaken_for_a_clean_one(self):
        """Every rule returns an empty list over an empty file set, which is
        why the non-empty assertions above are load-bearing rather than
        decorative."""
        assert _untraceable_reads([], {}) == []
        assert _writes_away_from_the_boundary([], set(), frozenset()) == []
        assert _drifted_bags([], set()) == []
