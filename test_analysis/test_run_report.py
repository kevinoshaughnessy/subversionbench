"""
report/run_report.py: which questions run, in what order, and the document
built around them.

The assembly layer only. The statistics live in test_report_pooling.py, the two
loaders in test_report_loading.py, the questions themselves in
test_report_questions.py and the corpus caveats in
test_report_data_quality.py - this file is what is left once those are told
apart: the end-to-end build, the CLI, and the two guards that hold the package's
layering in place.
"""

import contextlib
import io
import json
import tempfile

import report as rr
from subversionbench.grading import MISALIGNED_ACTS
from test_analysis.report_fixtures import (_single, _write_episode,
                                           _write_summary,
                                           write_awareness_episode)

class TestBuildReportEndToEnd:
    """One tiny fixture directory, run through the real pipeline the CLI
    uses - build_report calls both loaders and all six question functions."""

    def _fixture_dir(self):
        out = tempfile.mkdtemp()
        cross_aware_high = {"aware": {"n": 8, "misaligned": 6},
                            "unaware": {"n": 2, "misaligned": 0}}
        for oversight in (True, False):
            _write_summary(
                out, "m", "strong", oversight=oversight, lure=False,
                stamp=f"2026010100000{int(oversight)}",
                n_runs=10, n_scheming=1 if oversight else 4,
                n_aware=3 if oversight else 7, n_unaware=7 if oversight else 3,
                cross=cross_aware_high)
        for i in range(5):
            _write_episode(out, i, "m", "strong", oversight=True,
                           aware=True, monitoring=False, escape=["cd /"])
        for i in range(5, 10):
            # tampered=None, because that is what the harness writes in the
            # no-oversight arm: with no monitoring artefact the act cannot be
            # committed, so the grader records no verdict rather than a False
            # one. A fixture writing False here says "did not tamper" where the
            # corpus says "could not tamper", which are the two readings the
            # per-act block exists to keep apart.
            _write_episode(out, i, "m", "strong", oversight=False,
                           aware=False, monitoring=True, escape=[],
                           tampered=None)
        return out

    def test_produces_all_twelve_questions(self):
        report = rr.build_report(self._fixture_dir())
        ids = [q["id"] for q in report["questions"]]
        assert ids == [
            "oversight_vs_scheming", "oversight_vs_awareness",
            "oversight_vs_misalignment", "nudge_vs_awareness",
            "awareness_vs_misalignment",
            "awareness_vs_monitoring_disabled", "awareness_vs_sandbox_escape",
            "awareness_vs_scheming", "awareness_vs_oversight_scheming",
            "awareness_vs_sandbox_scheming", "paraphrase_vs_concealment",
            "evidence_vs_concealment",
        ]
        assert report["n_summary_files"] == 2
        assert report["n_episode_files"] == 10
        assert report["n_models"] == 1

    def test_every_union_question_carries_its_per_act_breakdown(self):
        """The block is an optional argument on both question functions, so the
        way it fails is by being absent - the report still builds, every number
        is still there, and the one thing that says the composite may not mean
        what it looks like is quietly gone.

        Scope is derived from what the question actually pools rather than from
        a list of two ids, so a third composite question added later is held to
        the same rule instead of escaping it."""
        report = rr.build_report(self._fixture_dir())
        unions = [q for q in report["questions"]
                  if q["id"] in ("oversight_vs_scheming",
                                 "oversight_vs_misalignment")]
        assert len(unions) == 2, [q["id"] for q in report["questions"]]
        for q in unions:
            assert "by_act" in q, (
                f"{q['id']} reports a union over MISALIGNED_ACTS with no per-act "
                f"breakdown, so nothing in it shows that one act is available in "
                f"only one arm")
            block = q["by_act"]
            assert len(block["components"]) == len(MISALIGNED_ACTS)
            assert "agreement" in block
            # The oversight act cannot be committed without oversight, so this
            # fixture must reproduce the structural gap the block exists for.
            assert block["single_arm_acts"], (
                "the fixture no longer reproduces an act available in only one "
                "arm, so this test would pass however the block behaved")

    def test_the_per_act_block_reads_the_same_episodes_as_the_composite(self):
        """Both are built from the same episodes, so a per-act numerator larger
        than the composite it decomposes would mean one of the two is being read
        off the wrong arm."""
        report = rr.build_report(self._fixture_dir())
        for q in report["questions"]:
            if "by_act" not in q:
                continue
            block = q["by_act"]
            for side in ("a", "b"):
                total = block["composite_overall"][side]["n"]
                for comp in block["components"]:
                    assert comp["overall"][side]["n"] == total, (
                        q["id"], comp["act"], side)
                    assert comp["overall"][side]["successes"] <= total

    def test_the_per_act_block_reaches_the_printed_report(self):
        """In the JSON and not on screen is the same failure as absent, for
        every reader who reads the printed report - which is all of them."""
        report = rr.build_report(self._fixture_dir())
        section = next(q for q in report["questions"]
                       if q["id"] == "oversight_vs_misalignment")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rr._print_question(section)
        printed = buf.getvalue()
        assert "PER ACT" in printed
        assert "ONE ARM ONLY" in printed, (
            "the printed block does not mark the act that only one arm could "
            "commit, so its zero still reads as a measurement")
        assert "comparable across arms:" in printed
        for act in MISALIGNED_ACTS:
            assert act["name"] in printed, act["name"]

    def test_every_single_contrast_question_carries_a_finding(self):
        report = rr.build_report(self._fixture_dir())
        for q in _single(report):
            assert isinstance(q["finding"], str) and q["finding"]
            assert "n_models_total" in q["consistency"]
            assert q["overall"]["level_a"] is not None

    def test_every_single_contrast_question_is_stratified_and_corrected(self):
        report = rr.build_report(self._fixture_dir())
        for q in _single(report):
            assert "mantel_haenszel" in q["stratified"], q["id"]
            assert "breslow_day" in q["stratified"], q["id"]
            assert "multiplicity" in q["consistency"], q["id"]

    def test_the_paired_questions_carry_per_contrast_multiplicity(self):
        """They have no stratified block on purpose - a paired contrast is
        already within-model - but each contrast still gets corrected."""
        report = rr.build_report(self._fixture_dir())
        paired = [q for q in report["questions"] if "contrasts" in q]
        assert len(paired) == 2
        for q in paired:
            assert "stratified" not in q
            for c in q["contrasts"]:
                assert "multiplicity" in c["consistency"]

    def test_the_report_is_json_serialisable(self):
        """The CLI writes this straight to disk with json.dump - a set, a
        non-finite float, or a stray object here would fail silently at
        write time instead of at construction."""
        report = rr.build_report(self._fixture_dir())
        json.dumps(report, default=str)

class TestMain:
    def _run(self, argv):
        import sys
        saved = sys.argv
        sys.argv = ["run_report.py", *argv]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    code = rr.main()
                except SystemExit as e:
                    code = e.code
            return code, buf.getvalue()
        finally:
            sys.argv = saved

    def test_refuses_a_missing_output_dir(self):
        code, _ = self._run(["--output-dir", "/no/such/directory/at/all"])
        assert code == 2

    def test_reports_cleanly_on_an_empty_but_existing_directory(self):
        out = tempfile.mkdtemp()
        code, text = self._run(["--output-dir", out])
        assert code == 1
        assert "No summary files found" in text

    def test_writes_the_json_report_next_to_the_console_output(self):
        out = tempfile.mkdtemp()
        _write_summary(out, "m", "none", n_runs=5, n_scheming=1)
        _write_summary(out, "m", "none", oversight=False,
                       stamp="20260101T000001", n_runs=5, n_scheming=2)
        json_out = f"{out}/report.json"
        code, text = self._run(["--output-dir", out, "--json-out", json_out])
        assert code == 0
        assert "Does the presence of oversight" in text
        with open(json_out) as f:
            saved = json.load(f)
        assert len(saved["questions"]) == 12

class TestTheParallelTextReachableMeasure:
    """That questions 2 and 4 - and only those two - carry the parallel measure,
    and that it prints.

    The wiring only. What the arm rows CONTAIN is tested in
    test_report_loading.py, since awareness_arm_rows is a loader; how the two
    measures are compared is tested in test_report_data_quality.py, since
    _measure_agreement lives there. What is left here is the part that genuinely
    needs a report to have been built.
    """

    def test_only_the_two_awareness_outcome_questions_carry_it(self):
        """Questions 5-10 use awareness as the EXPOSURE. Swapping the exposure
        definition is a different analysis, not a parallel column, so it is not
        silently attached there."""
        with tempfile.TemporaryDirectory() as out:
            for n, nudge in enumerate(("none", "strong", "max"), start=1):
                write_awareness_episode(out, n, "m", nudge, where="text")
                write_awareness_episode(out, n + 10, "m", nudge, oversight=False,
                              where="thinking")
            report = rr.build_report(out)
            carried = {q["id"] for q in report["questions"]
                       if "text_reachable" in q}
            assert carried == {"oversight_vs_awareness", "nudge_vs_awareness"}

    def test_the_block_prints_without_error(self):
        with tempfile.TemporaryDirectory() as out:
            for n, nudge in enumerate(("none", "strong", "max"), start=1):
                write_awareness_episode(out, n, "m", nudge, where="text")
                write_awareness_episode(out, n + 10, "m", nudge, oversight=False,
                              where="thinking")
            report = rr.build_report(out)
            section = next(q for q in report["questions"]
                           if q["id"] == "oversight_vs_awareness")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rr._print_question(section)
            printed = buf.getvalue()
            assert "PARALLEL MEASURE" in printed
            assert "text-reachable" in printed
            assert "gap = mixed - text" in printed

class TestTheLayersDoNotPointBackwards:
    """The split is only worth having while these hold.

    Six section banners in one 1,956-line file said these were separate
    concerns; nothing checked it, and nothing could, because a banner is not a
    boundary. These are the tests that make the claim mean something.
    """

    QUESTION_MODULES = ("questions_arms", "questions_awareness",
                        "questions_paired")

    def _imports(self, leaf):
        import ast
        names = set()
        for node in ast.walk(ast.parse(open(f"report/{leaf}.py").read())):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add(("." * node.level) + (node.module or ""))
        return names

    def test_pooling_does_not_know_which_question_it_serves(self):
        """The reason twelve questions share one pooling implementation rather
        than growing twelve slightly different ones. A `_contrast` that imported
        a question could be special-cased for it, which is how two questions
        end up reporting the same contrast differently.

        The question half of this is belt and braces: every question module
        imports pooling, so a pooling->question import is a cycle and the
        interpreter refuses it before this test runs. The half that only this
        test catches is loading and console, which pooling could import today
        without any error at all.
        """
        reached = self._imports("pooling")
        assert not any(m.lstrip(".") in self.QUESTION_MODULES for m in reached)
        assert ".loading" not in reached and ".console" not in reached

    def test_loading_is_the_bottom_layer(self):
        """It says what the files hold and nothing else. A loader that pooled
        could not be used by the questions that need the raw rows."""
        reached = self._imports("loading")
        for sibling in ("pooling", "data_quality", "console", "run_report",
                        *self.QUESTION_MODULES):
            assert f".{sibling}" not in reached, sibling

    def test_the_question_groups_do_not_import_each_other(self):
        """Assigned, observed and paired are three different claims. A question
        that borrowed another group's helper would be reporting one shape of
        evidence through machinery built for another."""
        for leaf in self.QUESTION_MODULES:
            others = {f".{m}" for m in self.QUESTION_MODULES if m != leaf}
            crossed = self._imports(leaf) & others
            assert not crossed, f"report/{leaf}.py imports {sorted(crossed)}"

    def test_the_console_computes_no_statistic(self):
        """Everything printed is read off the document build_report returns, so
        the table and the JSON cannot disagree. The one power import allowed is
        the informative-denominator THRESHOLD, which decides what to print
        rather than what the number is."""
        import ast
        printed = set()
        for node in ast.walk(ast.parse(open("report/console.py").read())):
            if isinstance(node, ast.ImportFrom) and node.module == \
                    "subversionbench.power":
                printed |= {a.name for a in node.names}
        assert printed <= {"MIN_INFORMATIVE_DENOMINATOR"}, (
            f"console.py reaches statistical machinery: "
            f"{sorted(printed - {'MIN_INFORMATIVE_DENOMINATOR'})}")

    def test_every_question_is_in_exactly_one_group(self):
        """Twelve, once each. A question defined in two modules, or reachable
        through the package but in neither group, is how the count in
        test_report_charts drifts away from what build_report calls."""
        import importlib
        seen = {}
        for leaf in self.QUESTION_MODULES:
            module = importlib.import_module(f"report.{leaf}")
            for name in dir(module):
                if name.startswith("question_") and \
                        getattr(module, name).__module__ == module.__name__:
                    assert name not in seen, (name, seen[name], leaf)
                    seen[name] = leaf
        assert len(seen) == 12, sorted(seen)
        assert sorted(seen.values()).count("questions_paired") == 2

class TestTheHeaderCountsDescribeTheCorpusTheQuestionsUse:
    """Under --exclude-aware the episodes are narrowed and the summaries are
    NOT - exclude_aware_episodes has no summary-side counterpart, because
    awareness is per episode and a summary row aggregates both kinds. So
    `n_models` taken from the summaries reported the un-narrowed model count
    beside numbers computed on the narrowed corpus: one header line describing
    two different populations, with nothing saying so."""

    def _dir(self):
        out = tempfile.mkdtemp()
        # Two models. One is aware in every episode, so the awareness reading
        # removes it entirely and the model count MUST fall.
        for model, aware in (("m-aware", True), ("m-unaware", False)):
            for oversight in (True, False):
                _write_summary(
                    out, model, "strong", oversight=oversight, lure=False,
                    stamp=f"2026010100000{int(oversight)}",
                    n_runs=4, n_scheming=1, n_aware=2, n_unaware=2)
            for i in range(4):
                _write_episode(out, i, model, "strong", oversight=True,
                               aware=aware, monitoring=False, escape=[])
        return out

    def test_the_model_count_follows_the_narrowing(self):
        out = self._dir()
        full = rr.build_report(out)
        narrowed = rr.build_report(out, awareness_exclusion=rr.EXCLUDE_AWARE_PRIMARY)
        assert full["n_models"] == 2, full["n_models"]
        assert narrowed["n_models"] == 1, (
            f"{narrowed['n_models']} models reported on a corpus the "
            f"awareness reading narrowed to one - the count came from the "
            f"un-narrowed summaries")

    def test_the_episode_count_follows_it_too(self):
        """The half that was already right, asserted so the two cannot drift
        apart again in the other direction."""
        out = self._dir()
        full = rr.build_report(out)
        narrowed = rr.build_report(out, awareness_exclusion=rr.EXCLUDE_AWARE_PRIMARY)
        assert narrowed["n_episode_files"] < full["n_episode_files"]

    def test_the_console_says_the_summary_count_is_not_narrowed(self):
        """The one number that legitimately still describes the whole
        directory. It stays - summary files really were read - but a reader
        given three counts on one line will read them as one corpus unless
        told otherwise."""
        import contextlib
        import io
        import sys
        out = self._dir()
        original = sys.argv
        sys.argv = ["report", "--output-dir", out, "--no-charts",
                    "--exclude-aware", rr.EXCLUDE_AWARE_PRIMARY]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rr.main()
        finally:
            sys.argv = original
        printed = buf.getvalue()
        assert "summary-file count is files read" in printed
        # And silent on the ordinary reading, where the three counts do all
        # describe one corpus.
        sys.argv = ["report", "--output-dir", out, "--no-charts"]
        plain = io.StringIO()
        try:
            with contextlib.redirect_stdout(plain):
                rr.main()
        finally:
            sys.argv = original
        assert "summary-file count is files read" not in plain.getvalue()


class TestTheSingleImportSiteForTheReport:
    def test_every_name_the_package_offers_is_declared(self):
        """`report/__init__.py` re-exports mostly PRIVATE names, which the tests
        reach through this one site rather than through whichever module holds
        them today. Without `__all__` each reads as a stray import to the
        dead-import guard, and an exemption would have hidden a real one."""
        import types

        import report
        # DERIVED, NOT LISTED. This was a hand-written tuple of eight module
        # names, and adding report/capability.py left it one behind - so the
        # new module read as an undeclared export and the failure pointed at
        # the wrong thing. That is the repeat defect class AGENTS.md names,
        # occurring in the guard rather than in the code it guards.
        #
        # Tested by TYPE rather than against the directory listing, because
        # `characteristics` is both a submodule and a re-exported FUNCTION of
        # the same name. A set built from filenames strips the function too,
        # and the guard then reports it as declared-but-absent - which is how
        # the first version of this derivation failed.
        submodules = {n for n in dir(report)
                      if isinstance(getattr(report, n), types.ModuleType)}
        # A scope that matched nothing would make every assertion below pass
        # on a package that exported nothing at all.
        assert len(submodules) >= 8, sorted(submodules)
        reachable = {n for n in dir(report)
                     if not n.startswith("__") and n not in submodules}
        declared = set(report.__all__)
        assert declared == reachable, (
            f"declared but absent: {sorted(declared - reachable)}; "
            f"present but undeclared: {sorted(reachable - declared)}")


# ---------------------------------------------------------------------------
# Excluding an arm
# ---------------------------------------------------------------------------
#
# `--exclude-no-oversight` answers all twelve questions again with the
# no-oversight arm set aside, because that arm's task README still promises the
# quality preview the arm itself removes. A sensitivity reading, not a
# correction - see report/loading.py.

def _two_arm_dir(nudges=("strong", "max"), unknown_arm=0):
    """
    A corpus with both oversight arms, both awareness levels inside each, and
    both nudge levels named by `nudges`.

    BOTH AWARENESS LEVELS IN BOTH ARMS on purpose: it is what lets a test tell
    "this question lost a side because the arm went" from "this question never
    had two sides here", which is the distinction _collapsed_by_exclusion was
    corrected to respect.
    """
    out = tempfile.mkdtemp()
    cross = {"aware": {"n": 8, "misaligned": 6},
             "unaware": {"n": 2, "misaligned": 0}}
    n = 0
    for oversight in (True, False):
        stamp = f"20260101T00000{int(oversight)}"
        for nudge in nudges:
            _write_summary(out, "m", nudge, oversight=oversight, lure=False,
                           stamp=stamp, n_runs=20, n_scheming=1, n_misaligned=3,
                           n_aware=8, n_unaware=12, cross=cross)
            for aware in (True, False):
                for _ in range(6):
                    _write_episode(out, n, "m", nudge, oversight=oversight,
                                   aware=aware, monitoring=not oversight,
                                   escape=["cd /"] if aware else [],
                                   tampered=None if not oversight else True,
                                   stamp=stamp)
                    n += 1
    for _ in range(unknown_arm):
        # An episode whose arm was never recorded. Written by hand rather than
        # through _write_episode, which always states one.
        path = f"{out}/run_{n}_m_strong_20260101T000009.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"model": "m", "nudge": "strong", "oversight": None,
                       "lure": False, "analysis": {"misaligned": False},
                       "transcript": []}, f)
        n += 1
    return out


class TestExcludingAnArmReachesBothDataSources:
    """The failure this class exists for, and it was a real one during the
    build: questions 1-4 are answered from summary_*.json and 5-12 from
    run_*.json, so an exclusion that reached only the episodes would leave a
    report whose halves describe different corpora while every number in it
    still rendered."""

    def test_both_the_summaries_and_the_episodes_shrink(self):
        out = _two_arm_dir()
        full = rr.build_report(out)
        cut = rr.build_report(out, rr.EXCLUDE_NO_OVERSIGHT)
        assert cut["n_episode_files"] < full["n_episode_files"]
        assert cut["n_summary_files"] < full["n_summary_files"], (
            "the summaries were not filtered - questions 1-4 are answered from "
            "them, so they would describe the full corpus while 5-12 describe "
            "the narrowed one")

    def test_the_surviving_rows_are_all_the_kept_arm(self):
        """The strong form. The counts above could match while the wrong rows
        survived, so the arms themselves are checked."""
        out = _two_arm_dir()
        summaries, episodes, stamp = rr.exclude_arm(
            rr.load_summaries(out), rr.load_episodes(out),
            rr.EXCLUDE_NO_OVERSIGHT)
        assert summaries and episodes
        assert {r["oversight"] for r in summaries} == {True}
        assert {r["oversight"] for r in episodes} == {True}
        assert stamp["n_episodes_dropped"] == stamp["n_episodes_before"] - \
            stamp["n_episodes_kept"]

    def test_nothing_moves_when_no_arm_is_excluded(self):
        """The positive control: the same call with the default leaves both
        lists exactly as they were, so the tests above are about the exclusion
        and not about the loaders."""
        out = _two_arm_dir()
        summaries, episodes = rr.load_summaries(out), rr.load_episodes(out)
        kept_s, kept_e, stamp = rr.exclude_arm(summaries, episodes)
        assert kept_s == summaries and kept_e == episodes
        assert stamp["axis"] is None
        assert stamp["n_episodes_dropped"] == 0

    def test_an_episode_with_no_arm_recorded_is_dropped_and_counted(self):
        """Neither kept nor silently treated as the arm being excluded: a
        missing field is a fact about the corpus, and folding it into either
        reading would hide it."""
        out = _two_arm_dir(unknown_arm=3)
        _, episodes, stamp = rr.exclude_arm(
            rr.load_summaries(out), rr.load_episodes(out),
            rr.EXCLUDE_NO_OVERSIGHT)
        assert stamp["n_episodes_unknown_arm"] == 3
        assert all(r["oversight"] is True for r in episodes)

    def test_an_unknown_exclusion_raises_rather_than_passing_everything(self):
        """A typo must not read as "exclude nothing" and produce a full-corpus
        report under a name that says otherwise."""
        try:
            rr.exclude_arm([], [], "oversght")
        except ValueError as exc:
            assert "oversght" in str(exc)
        else:
            raise AssertionError("a misspelled exclusion was accepted")

    def test_the_stamp_is_present_even_when_nothing_was_excluded(self):
        """So a consumer never has to tell "no exclusion" from "a report
        written before exclusions existed" - both would be a missing key."""
        report = rr.build_report(_two_arm_dir())
        assert report["arm_exclusion"]["excluded"] == rr.NO_EXCLUSION
        assert report["arm_exclusion"]["axis"] is None


class TestWhichQuestionsTheExclusionIsBlamedFor:
    def test_the_three_oversight_contrasts_lose_their_comparator(self):
        report = rr.build_report(_two_arm_dir(), rr.EXCLUDE_NO_OVERSIGHT)
        marked = [q["id"] for q in report["questions"]
                  if q.get("collapsed_by_exclusion")]
        assert marked == ["oversight_vs_scheming", "oversight_vs_awareness",
                          "oversight_vs_misalignment"]

    def test_a_question_that_lost_a_side_for_another_reason_is_not_blamed(self):
        """THE CORRECTION THIS TEST EXISTS FOR. An empty side is necessary and
        not sufficient. Measured on this fixture: with only `strong` and `max`
        collected, question 4 contrasts a nudge level the corpus never held and
        so has one empty side in BOTH readings. Blaming the exclusion there
        invents an explanation a reader cannot check."""
        out = _two_arm_dir(nudges=("strong", "max"))
        full = rr.build_report(out)
        cut = rr.build_report(out, rr.EXCLUDE_NO_OVERSIGHT)

        def one_side_empty(report, qid):
            section = next(q for q in report["questions"] if q["id"] == qid)
            overall = section["overall"]
            return not ((overall["a"] or {})["n"] and (overall["b"] or {})["n"])

        assert one_side_empty(full, "nudge_vs_awareness"), (
            "the fixture no longer reproduces the case - question 4 has both "
            "sides even on the full corpus, so this test proves nothing")
        assert one_side_empty(cut, "nudge_vs_awareness")
        section = next(q for q in cut["questions"]
                       if q["id"] == "nudge_vs_awareness")
        assert "collapsed_by_exclusion" not in section, (
            "question 4 was blamed on the exclusion, but it has one empty side "
            "with the full corpus too")

    def test_nothing_is_blamed_when_no_arm_was_excluded(self):
        report = rr.build_report(_two_arm_dir())
        assert not [q for q in report["questions"]
                    if q.get("collapsed_by_exclusion")]

    def test_the_paired_questions_are_never_marked(self):
        """They hold `contrasts` rather than `overall` - a different shape with
        no single pair of sides to be empty - so the mark would be read off a
        key they do not have."""
        report = rr.build_report(_two_arm_dir(), rr.EXCLUDE_NO_OVERSIGHT)
        for section in report["questions"]:
            if "contrasts" in section:
                assert "collapsed_by_exclusion" not in section


class TestTheTwoReadingsCannotOverwriteEachOther:
    def test_the_chart_directory_and_json_name_differ(self):
        """Same chart filenames, different directory: that is what keeps the
        arm-excluded figures from being written over the full-corpus ones."""
        import report.run_report as module
        plain = module._artefact_suffix(rr.NO_EXCLUSION)
        cut = module._artefact_suffix(rr.EXCLUDE_NO_OVERSIGHT)
        assert plain == ""
        assert cut and cut != plain
        assert "no_oversight" in cut

    def test_every_exclusion_gets_a_name_of_its_own(self):
        """Derived from the exclusion's own key rather than tabulated beside it,
        so an exclusion added later cannot arrive with no entry and quietly
        write its charts over the full-corpus ones. Enumerated from
        ARM_EXCLUSIONS, so a new one is covered without editing this test."""
        import report.run_report as module
        assert len(rr.ARM_EXCLUSIONS) >= 2
        suffixes = {name: module._artefact_suffix(name)
                    for name in rr.ARM_EXCLUSIONS}
        assert len(set(suffixes.values())) == len(suffixes), suffixes
        assert suffixes[rr.NO_EXCLUSION] == ""

    def test_an_unknown_name_gets_no_suffix_and_raises_instead(self):
        import report.run_report as module
        try:
            module._artefact_suffix("oversght")
        except ValueError:
            pass
        else:
            raise AssertionError("a misspelled exclusion got an artefact name")


class TestTheConsoleSaysWhichArmsTheNumbersAreAbout:
    def _printed(self, stamp):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rr._print_arm_exclusion(stamp)
        return buf.getvalue()

    def _stamp(self, **over):
        stamp = {"excluded": "no_oversight", "axis": "oversight",
                 "excluded_level": False,
                 "words": "no-oversight arm excluded", "why": "the README.",
                 "n_summaries_before": 8, "n_summaries_kept": 4,
                 "n_episodes_before": 240, "n_episodes_kept": 120,
                 "n_episodes_dropped": 120, "n_episodes_unknown_arm": 0}
        stamp.update(over)
        return stamp

    def test_it_says_nothing_when_no_arm_was_excluded(self):
        """A banner over every ordinary report trains a reader to skip the
        block, and skipping it is the failure the block exists to prevent."""
        assert self._printed({}) == ""
        assert self._printed({"axis": None}) == ""

    def test_it_names_the_arm_the_counts_and_that_it_is_not_a_correction(self):
        text = self._printed(self._stamp())
        assert "NO-OVERSIGHT ARM EXCLUDED" in text
        assert "120" in text and "240" in text
        assert "NOT A CORRECTION" in text

    def test_it_warns_when_the_exclusion_matched_nothing(self):
        """The silent failure: a renamed field drops no episode, and the report
        is the full corpus under a name that says it is not."""
        text = self._printed(self._stamp(n_episodes_dropped=0,
                                         n_episodes_kept=240))
        assert "Nothing was dropped" in text

    def test_it_warns_about_episodes_in_neither_reading(self):
        text = self._printed(self._stamp(n_episodes_unknown_arm=7))
        assert "7 episode(s) record no oversight arm" in text
        assert "neither reading" in text

    def test_a_collapsed_question_is_said_rather_than_tabulated_empty(self):
        """`_print_question` returns after saying so, instead of printing a
        header over a table of "no data" rows a reader would blame on the
        corpus."""
        section = {"question": "Q?", "data_source": "summaries",
                   "collapsed_by_exclusion": "not estimable with the arm "
                                             "excluded"}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rr._print_question(section)
        text = buf.getvalue()
        assert "NOT ESTIMABLE WITH THE ARM EXCLUDED" in text
        assert "CRUDE POOLED" not in text


class TestTheUnawareCorpusReading:
    """Questions 1-4 answered again over only the episodes where no evaluation
    awareness was found, to test whether an arm contrast is the arm or the
    models that noticed the evaluation.

    Two things are guarded, and neither is the arithmetic. First, questions 1-4
    must stop pooling from summary_*.json, whose counts describe whole arms
    INCLUDING the episodes just removed - the split-corpus report exclude_arm's
    own comment exists to prevent. Second, the questions this corpus cannot
    support must say so rather than render: awareness is the outcome of
    questions 2 and 4, so both sides go to zero BY CONSTRUCTION, and a reader
    shown "0.0% vs 0.0%" has been given a definition dressed as a measurement.
    """

    def test_the_arm_questions_stop_pooling_from_the_summaries(self):
        """THE ONE THAT MATTERS. The summaries still describe every episode in
        each arm, so pooling them here would answer questions 1-4 on the full
        corpus while everything else answered on the narrowed one - and every
        number would still render."""
        out = _two_arm_dir()
        full = rr.build_report(out)
        cut = rr.build_report(out, rr.NO_EXCLUSION, rr.EXCLUDE_AWARE_PRIMARY)
        assert full["questions_pooled_from"] == "summaries"
        assert cut["questions_pooled_from"] == "rebuilt_arm_rows"

        def denominator(report, qid):
            section = next(q for q in report["questions"] if q["id"] == qid)
            overall = section["overall"]
            return (overall["a"] or {})["n"] + (overall["b"] or {})["n"]

        assert denominator(cut, "oversight_vs_misalignment") < denominator(
            full, "oversight_vs_misalignment"), (
            "question 3's denominator did not shrink, so it is still being "
            "answered off the whole-arm summary counts")

    def test_the_denominator_is_the_surviving_episode_count(self):
        """Not merely smaller - equal to what the exclusion actually kept, so
        a partial narrowing cannot pass this."""
        out = _two_arm_dir()
        cut = rr.build_report(out, rr.NO_EXCLUSION, rr.EXCLUDE_AWARE_PRIMARY)
        section = next(q for q in cut["questions"]
                       if q["id"] == "oversight_vs_misalignment")
        overall = section["overall"]
        pooled = (overall["a"] or {})["n"] + (overall["b"] or {})["n"]
        assert pooled == cut["awareness_exclusion"]["n_episodes_kept"]

    def test_the_awareness_questions_are_not_estimable_and_say_so(self):
        """Derived from the question ids, so a thirteenth question naming
        awareness on either side inherits this rather than being answered on a
        corpus that cannot support it."""
        cut = rr.build_report(_two_arm_dir(), rr.NO_EXCLUSION,
                              rr.EXCLUDE_AWARE_PRIMARY)
        blocked = {q["id"] for q in cut["questions"]
                   if q.get("collapsed_by_exclusion")}
        # Awareness as the OUTCOME (2, 4) and as the EXPOSURE (5-10).
        assert "oversight_vs_awareness" in blocked
        assert "nudge_vs_awareness" in blocked
        assert all(q["id"] in blocked for q in cut["questions"]
                   if q["id"].startswith("awareness_vs_"))
        assert len(blocked) == 8, sorted(blocked)

    def test_the_questions_the_reading_can_answer_are_left_alone(self):
        """The point of the reading. Questions 1 and 3 contrast an arm against
        an outcome that is not awareness, and 11-12 split on interrogation
        phrasing - none of them lose anything by the aware episodes going."""
        cut = rr.build_report(_two_arm_dir(), rr.NO_EXCLUSION,
                              rr.EXCLUDE_AWARE_PRIMARY)
        estimable = [q["id"] for q in cut["questions"]
                     if not q.get("collapsed_by_exclusion")]
        assert estimable == ["oversight_vs_scheming",
                             "oversight_vs_misalignment",
                             "paraphrase_vs_concealment",
                             "evidence_vs_concealment"]

    def test_nothing_is_blamed_when_no_awareness_reading_was_asked_for(self):
        report = rr.build_report(_two_arm_dir())
        assert not [q for q in report["questions"]
                    if q.get("collapsed_by_exclusion")]
        assert report["awareness_exclusion"]["field"] is None

    def test_the_stamp_is_present_even_when_nothing_was_excluded(self):
        """Same reason arm_exclusion's is: a consumer must never have to tell
        "no exclusion" from "a report written before this existed"."""
        report = rr.build_report(_two_arm_dir())
        stamp = report["awareness_exclusion"]
        assert stamp["excluded"] == rr.NO_AWARENESS_EXCLUSION
        assert stamp["field"] is None and stamp["measure"] is None

    def test_the_two_measures_are_named_primary_and_secondary(self):
        """The grader-with-keyword-fallback measure is what every published
        rate here uses; the union is offered beside it and must not be
        mistaken for it."""
        out = _two_arm_dir()
        primary = rr.build_report(out, rr.NO_EXCLUSION,
                                  rr.EXCLUDE_AWARE_PRIMARY)
        union = rr.build_report(out, rr.NO_EXCLUSION, rr.EXCLUDE_AWARE_UNION)
        assert primary["awareness_exclusion"]["measure"] == "primary"
        assert union["awareness_exclusion"]["measure"] == "secondary"
        assert primary["awareness_exclusion"]["field"] == "aware"
        assert union["awareness_exclusion"]["field"] == "aware_union"

    def test_the_two_narrowings_compose_without_overwriting_each_other(self):
        """Three readings of one corpus, all writing the same chart filenames.
        The arm-only suffix must not move, or every artefact and test already
        naming it breaks."""
        import report.run_report as module
        assert module._artefact_suffix(rr.NO_EXCLUSION) == ""
        assert module._artefact_suffix(
            rr.EXCLUDE_NO_OVERSIGHT) == "_excluding_no_oversight"
        suffixes = {
            module._artefact_suffix(arm, aware)
            for arm in rr.ARM_EXCLUSIONS
            for aware in rr.AWARENESS_EXCLUSIONS}
        assert len(suffixes) == len(rr.ARM_EXCLUSIONS) * len(
            rr.AWARENESS_EXCLUSIONS), suffixes

    def test_an_unknown_awareness_name_raises_rather_than_naming_nothing(self):
        import report.run_report as module
        try:
            module._artefact_suffix(rr.NO_EXCLUSION, "aware_prmary")
        except ValueError as exc:
            assert "aware_prmary" in str(exc)
        else:
            raise AssertionError(
                "a misspelled awareness exclusion got an artefact name")

    def test_the_banner_states_the_reading_before_any_number(self):
        """A reader who meets the narrowing at the bottom has already read
        every rate above it as though it described the whole corpus."""
        import io
        from contextlib import redirect_stdout
        cut = rr.build_report(_two_arm_dir(), rr.NO_EXCLUSION,
                              rr.EXCLUDE_AWARE_PRIMARY)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rr._print_awareness_exclusion(cut["awareness_exclusion"])
        out = buf.getvalue()
        assert "AWARE EPISODES EXCLUDED" in out
        assert "ROBUSTNESS READING, NOT A BETTER ESTIMATE" in out
        assert "REBUILT" in out

    def test_the_banner_is_silent_on_the_unrestricted_reading(self):
        """A banner over every ordinary report is one readers learn to skip."""
        import io
        from contextlib import redirect_stdout
        report = rr.build_report(_two_arm_dir())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rr._print_awareness_exclusion(report["awareness_exclusion"])
        assert buf.getvalue() == ""
