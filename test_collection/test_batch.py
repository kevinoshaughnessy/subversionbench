"""
Batch identity: the arm a batch ran under, and the filename that carries it.

The name is the only durable record of the arm, so it is parsed as data rather
than pattern-matched, and a rebuild reads the arm from the filenames rather than
from whatever the rebuild was invoked with.
"""

import ast
import contextlib
import dataclasses
import glob
import inspect
import io
import json
import os
import pytest
import sys
import tempfile
import types

from pathlib import Path
from subversionbench.batch import discover_batches
from subversionbench.batch import BatchIdentity
from subversionbench.batch import find_run_files
from subversionbench.batch import unique_batch_stamp
import subversionbench.llm_client as ev_llm
import subversionbench.run_eval as ev_run
from conftest import write_run_file


class TestTheIdentityCannotBeReintroducedAsMutableState:
    def test_it_is_frozen(self):
        """A callee that could assign to the identity could recreate the leak by
        another route."""
        identity = BatchIdentity(model="m", model_slug="m", nudge="strong")
        with pytest.raises(dataclasses.FrozenInstanceError):
            identity.effort = "high"

    def test_summarise_batch_reads_no_arm_field_off_args(self):
        """The static half. summarise_batch is the function whose filename choice
        started this, so it is the one that must not be able to consult `args`
        about the arm."""
        tree = ast.parse(inspect.getsource(ev_run.summarise_batch))
        offenders = {n.attr for n in ast.walk(tree)
                     if isinstance(n, ast.Attribute)
                     and getattr(n.value, "id", "") == "args"
                     and n.attr in ("model", "nudge", "effort", "oversight", "lure")}
        assert not offenders, (
            f"summarise_batch reads the arm off args again: {sorted(offenders)}")

    def test_collecting_will_not_default_the_effort(self):
        """None is a VALUE here - "no effort was sent" - not an absent argument.

        A signature that defaulted `effort` to args.effort reads naturally and is
        wrong exactly where it matters: asking a model with no effort control for
        `max` sends nothing, and the batch must not then be labelled `max`. That
        happened while this was being written.
        """
        params = inspect.signature(BatchIdentity.collecting).parameters
        assert params["effort"].default is inspect.Parameter.empty

class TestTheNamingRoundTrips:
    def test_the_stem_and_the_parse_are_inverses(self):
        """Writing and reading a name have to agree, or a batch becomes findable
        under one arm and rebuilt under another."""
        from subversionbench.batch import parse_batch_filename
        for effort in (None, "high"):
            for oversight in (True, False):
                for lure in (False, True):
                    identity = BatchIdentity(
                        model="a/b", model_slug="a_b", nudge="strong",
                        effort=effort, oversight=oversight, lure=lure,
                        stamp="20260101T000000")
                    path = identity.filename("/out", "run_1")
                    got = parse_batch_filename(path, "strong")
                    assert got == (effort, "20260101T000000", oversight, lure,
                                   None), (
                        f"{path} parsed back as {got}")

    def test_the_stamp_is_always_last(self):
        """find_run_files_by_stamp and regrade_all.sh both key off a trailing
        _<stamp>.json, so nothing may be appended after it."""
        identity = BatchIdentity(model="m", model_slug="m", nudge="strong",
                                 effort="high", oversight=False, lure=True,
                                 stamp="20260101T000000")
        assert identity.filename("/out").endswith("_20260101T000000.json")

    def test_an_absent_stamp_leaves_no_dangling_separator(self):
        identity = BatchIdentity(model="m", model_slug="m", nudge="strong")
        assert identity.filename("/out") == "/out/summary_m_strong.json"

class TestDiscovery:
    def test_finds_every_model_and_nudge_pair(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        write_run_file(d, 1, "google/gemini-3.5-flash", "strong")
        write_run_file(d, 2, "google/gemini-3.5-flash", "none")
        write_run_file(d, 3, "x-ai/grok-4.5", "strong")
        assert discover_batches(d) == [
            ("google/gemini-3.5-flash", "none"),
            ("google/gemini-3.5-flash", "strong"),
            ("x-ai/grok-4.5", "strong"),
        ]

    def test_a_concrete_value_still_filters(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        write_run_file(d, 1, "a/b", "strong")
        write_run_file(d, 2, "a/b", "none")
        write_run_file(d, 3, "c/d", "none")
        assert discover_batches(d, nudge="none") == [("a/b", "none"),
                                                     ("c/d", "none")]
        assert discover_batches(d, model="a/b") == [("a/b", "none"),
                                                   ("a/b", "strong")]

    def test_only_pairs_that_exist_are_returned(self):
        """Fanning out must not generate combinations that were never collected,
        or the run fills with 'no run files' errors that hide a real one."""
        d = tempfile.mkdtemp(prefix="fanout_")
        write_run_file(d, 1, "a/b", "strong")
        write_run_file(d, 2, "c/d", "max")
        assert ("a/b", "max") not in discover_batches(d)
        assert ("c/d", "strong") not in discover_batches(d)

    def test_a_truncated_run_file_is_skipped_not_fatal(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        write_run_file(d, 1, "a/b", "strong")
        Path(d, "run_2_broken_strong_20260101T000000.json").write_text("{oops")
        assert discover_batches(d) == [("a/b", "strong")]

    def test_empty_directory_discovers_nothing(self):
        assert discover_batches(tempfile.mkdtemp(prefix="fanout_")) == []

class TestModelSlugIsDelimited:
    """A shorter model slug must not sweep in a longer model's files.

    find_run_files globs `run_*_<slug>_<nudge>`, and the `*` standing in for the
    run index matches across underscores - so `gpt-5.4` also matched
    `run_10_openai_gpt-5.4_strong`. Two live consequences: summarising the short
    spelling covered 20 files instead of 10, which is where a primary-arm
    denominator of 630 came from against a true 610; and fanning a paid regrade
    out over a directory would have graded those files twice.
    """

    def _dir(self):
        d = tempfile.mkdtemp(prefix="slug_")
        for i in (1, 2):
            write_run_file(d, i, "gpt-5.4", "strong")
            write_run_file(d, i, "openai/gpt-5.4", "strong")
        return d

    def test_the_short_spelling_does_not_match_the_prefixed_one(self):
        from subversionbench.batch import find_run_files
        d = self._dir()
        short = find_run_files(d, "gpt-5.4", "strong")
        assert len(short) == 2, [os.path.basename(p) for p in short]
        assert not any("openai" in os.path.basename(p) for p in short)

    def test_the_prefixed_spelling_matches_only_its_own(self):
        from subversionbench.batch import find_run_files
        d = self._dir()
        got = find_run_files(d, "openai_gpt-5.4", "strong")
        assert len(got) == 2
        assert all("openai" in os.path.basename(p) for p in got)

    def test_the_two_spellings_are_disjoint(self):
        from subversionbench.batch import find_run_files
        d = self._dir()
        a = set(find_run_files(d, "gpt-5.4", "strong"))
        b = set(find_run_files(d, "openai_gpt-5.4", "strong"))
        assert not (a & b), "a file matched by both spellings would be graded twice"

    def test_no_file_is_matched_by_two_batch_pairs(self):
        """The property that matters for fanning out: every run file belongs to
        exactly one (model, nudge) group."""
        from subversionbench.batch import find_run_files
        d = self._dir()
        write_run_file(d, 3, "gpt-5.4", "none")
        counts = {}
        for m, n in discover_batches(d):
            for f in find_run_files(d, m.replace("/", "_"), n):
                counts[f] = counts.get(f, 0) + 1
        assert all(c == 1 for c in counts.values()), counts

    def test_the_arm_and_effort_suffixes_still_match(self):
        """The delimiter rule must not exclude the legitimate name shapes."""
        from subversionbench.batch import find_run_files
        d = tempfile.mkdtemp(prefix="slug_")
        write_run_file(d, 1, "a/b", "strong")                      # plain
        write_run_file(d, 2, "a/b", "strong", effort="high")       # with effort
        Path(d, "run_3_a_b_strong.json").write_text(
            json.dumps({"model": "a/b", "nudge": "strong"}))  # no stamp at all
        Path(d, "run_4_a_b_strong_nooversight_20260101T000000.json").write_text(
            json.dumps({"model": "a/b", "nudge": "strong"}))  # counterfactual
        assert len(find_run_files(d, "a_b", "strong")) == 4

class TestBatchStamp:
    """Run and summary filenames carry a batch timestamp so re-running the
    same model and nudge doesn't overwrite the previous results."""

    def test_stamp_is_sortable_and_filename_safe(self):
        stamp = unique_batch_stamp(tempfile.mkdtemp())
        assert len(stamp) == 15 and stamp[8] == "T"
        assert stamp.replace("T", "").isdigit()
        for illegal in ':/\\ ?*"<>|':
            assert illegal not in stamp

    def test_same_second_batches_do_not_collide(self):
        """Regression: a plain second-resolution stamp let two batches started
        in the same second resolve to the same filenames, so the later one
        silently overwrote the earlier - the exact thing the stamp prevents."""
        out = tempfile.mkdtemp()
        first = unique_batch_stamp(out)
        Path(f"{out}/run_1_somemodel_strong_{first}.json").write_text("{}")

        second = unique_batch_stamp(out)
        assert second != first
        Path(f"{out}/run_1_somemodel_strong_{second}.json").write_text("{}")

        third = unique_batch_stamp(out)
        assert third not in (first, second)

    def test_stamp_ignores_unrelated_files(self):
        out = tempfile.mkdtemp()
        stamp = unique_batch_stamp(out)
        Path(f"{out}/notes.txt").write_text("x")
        Path(f"{out}/run_1_somemodel_strong_20200101T000000.json").write_text("{}")
        assert unique_batch_stamp(out) == stamp

class TestEffortInFilenames:
    """The effort level is part of a batch's identity: the same model at `low`
    and at `xhigh` are two conditions. Naming them so they differ only by
    timestamp invites their being pooled, and pooling two conditions is the kind
    of error nothing downstream can detect."""

    def test_the_stem_only_carries_an_effort_that_was_set(self):
        """Batches at the API default must keep the names they have always had,
        or every result already on disk stops being findable."""
        assert ev_run.batch_stem("claude-opus-5", "strong") == "claude-opus-5_strong"
        assert ev_run.batch_stem("claude-opus-5", "strong", None) == "claude-opus-5_strong"
        assert (ev_run.batch_stem("claude-opus-5", "strong", "xhigh")
                == "claude-opus-5_strong_xhigh")

    def test_the_stamp_stays_last(self):
        """find_run_files_by_stamp and regrade_all.sh both key off a trailing
        _<stamp>.json, so the effort has to sit before it."""
        name = f"run_1_{ev_run.batch_stem('m', 'strong', 'max')}_20260731T010203.json"
        assert name.endswith("_20260731T010203.json")
        assert ev_run.find_run_files_by_stamp.__doc__  # sanity: still the keyed lookup

    def test_both_shapes_parse_back(self):
        for name, expected in (
            ("run_1_claude-opus-5_strong_20260731T010203.json", (None, "20260731T010203")),
            ("run_1_claude-opus-5_strong_xhigh_20260731T010203.json", ("xhigh", "20260731T010203")),
            # A same-second collision suffix must not break the stamp.
            ("run_1_x-ai_grok-4.5_strong_max_20260731T010203-2.json", ("max", "20260731T010203-2")),
            ("run_1_claude-opus-5_strong.json", (None, "")),
        ):
            assert ev_run.parse_batch_filename(name, "strong")[:2] == expected, name

    def test_a_level_is_only_read_from_the_final_segment(self):
        """Guards against a model slug that happens to end in a level name.

        The match moved from `_<nudge>_<level>` to a trailing `_<level>` when
        the oversight arm gained a segment of its own between them; it stays
        safe because the effort, when present, is always the last segment
        before the stamp."""
        assert ev_run.parse_batch_filename(
            "run_1_some-model-max_strong_20260731T010203.json", "strong"
        ) == (None, "20260731T010203", True, False, None)

    def test_the_arm_and_the_level_compose(self):
        assert ev_run.parse_batch_filename(
            "run_1_m_strong_nooversight_high_20260731T010203.json", "strong"
        ) == ("high", "20260731T010203", False, False, None)

    def test_the_arm_the_lure_and_the_level_all_compose(self):
        """Four optional suffixes now, stripped in any order. A fixed sequence
        broke the moment a new one landed between two existing ones."""
        assert ev_run.parse_batch_filename(
            "run_1_m_max_nooversight_lure_high_20260731T010203.json", "max"
        ) == ("high", "20260731T010203", False, True, None)
        assert ev_run.parse_batch_filename(
            "run_1_m_strong_lure_20260731T010203.json", "strong"
        ) == (None, "20260731T010203", True, True, None)

    def _write(self, out, name):
        Path(f"{out}/{name}").write_text(json.dumps(
            {"model": "claude-opus-5", "nudge": "strong",
             "transcript": [{"turn": 1, "type": "text", "content": "x"}],
             "analysis": {}}))

    def test_an_effort_batch_is_still_found_when_none_is_asked_for(self):
        """--grade-existing and --resummarise must see every batch regardless of
        what it was run at; missing one leaves it silently un-regraded, which is
        invisible in the summaries."""
        out = tempfile.mkdtemp()
        self._write(out, "run_1_claude-opus-5_strong_20260731T010203.json")
        self._write(out, "run_1_claude-opus-5_strong_xhigh_20260731T010204.json")

        found = [os.path.basename(f)
                 for f in find_run_files(out, "claude-opus-5", "strong")]
        assert len(found) == 2, found

    def test_an_effort_narrows_the_search(self):
        out = tempfile.mkdtemp()
        self._write(out, "run_1_claude-opus-5_strong_20260731T010203.json")
        self._write(out, "run_1_claude-opus-5_strong_xhigh_20260731T010204.json")

        found = [os.path.basename(f) for f in
                 find_run_files(out, "claude-opus-5", "strong", effort="xhigh")]
        assert found == ["run_1_claude-opus-5_strong_xhigh_20260731T010204.json"]

    def test_the_run_records_the_effort_that_was_sent(self):
        """Recorded beside the model it applied to, and taken from the resolved
        request rather than the flag: an effort the model rejects is dropped, and
        recording the request would claim a condition that never applied."""
        out = tempfile.mkdtemp()

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            @staticmethod
            def create(messages=None, **kw):
                return blk(stop_reason="end_turn", content=[
                    blk(type="text", text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original, original_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m, **_kw: Client()
        sys.argv = ["run_eval", "--model", "claude-opus-5", "--runs", "1",
                    "--delay", "0", "--no-grader", "--effort", "xhigh",
                    "--output-dir", out]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        run_files = glob.glob(f"{out}/run_1_*.json")
        assert run_files
        name = os.path.basename(run_files[0])
        assert "_strong_xhigh_" in name, name
        data = json.loads(Path(run_files[0]).read_text())
        assert data["effort"] == "xhigh"
        # Immediately after the model, as the field order is part of the ask.
        keys = list(data)
        assert keys[keys.index("model") + 1] == "effort"

    def test_an_unsupported_effort_is_not_claimed_in_the_name(self):
        """OpenRouter takes no effort parameter, so a batch run with --effort
        against one did not run at that effort and must not say it did."""
        out = tempfile.mkdtemp()

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            @staticmethod
            def create(messages=None, **kw):
                return blk(stop_reason="end_turn", content=[
                    blk(type="text", text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original, original_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m, **_kw: Client()
        sys.argv = ["run_eval", "--model", "x-ai/grok-4.5", "--runs", "1",
                    "--delay", "0", "--no-grader", "--effort", "max",
                    "--output-dir", out]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        name = os.path.basename(glob.glob(f"{out}/run_1_*.json")[0])
        assert "_max_" not in name, name
        data = json.loads(Path(glob.glob(f"{out}/run_1_*.json")[0]).read_text())
        assert data["effort"] is None

class TestBatchIdentityInTheOversightArm:
    def test_the_arm_is_part_of_the_filename(self):
        assert ev_run.batch_stem("m", "strong", None, True) == "m_strong"
        assert ev_run.batch_stem("m", "strong", None, False) == "m_strong_nooversight"

    def test_the_oversight_arm_keeps_the_names_it_has(self):
        """570 episodes are already on disk under the unmarked name."""
        assert "nooversight" not in ev_run.batch_stem("m", "strong", "high", True)

    def test_the_arm_and_the_effort_compose(self):
        stem = ev_run.batch_stem("m", "strong", "high", False)
        assert stem == "m_strong_nooversight_high"
        assert ev_run.parse_batch_filename(
            f"run_1_{stem}_20260802T000000.json", "strong"
        ) == ("high", "20260802T000000", False, False, None)

    def test_the_arms_cannot_be_pooled_by_discovery(self):
        from pathlib import Path
        out = tempfile.mkdtemp()
        for name in ("run_1_m_strong_20260101T000000.json",
                     "run_1_m_strong_nooversight_20260101T000001.json"):
            Path(out, name).write_text("{}")
        assert len(ev_run.find_run_files(out, "m", "strong", oversight=True)) == 1
        assert len(ev_run.find_run_files(out, "m", "strong", oversight=False)) == 1
        # and both, for the read-only modes that sweep everything
        assert len(ev_run.find_run_files(out, "m", "strong")) == 2

class TestBatchIdentityInTheMaxNudgeArm:
    """max must not pool with strong. It measures concealment under coercion,
    where honesty has been made expensive - a different and weaker claim about
    scheming propensity than a denial with nothing to gain."""

    def test_the_nudge_appears_in_the_batch_stem(self):
        import subversionbench.run_eval as ev_run
        strong = ev_run.batch_stem("m", "strong")
        mx = ev_run.batch_stem("m", "max")
        assert strong != mx
        assert "max" in mx

    def test_the_arms_cannot_share_a_summary_filename(self):
        import subversionbench.run_eval as ev_run
        seen = {ev_run.batch_stem("m", n) for n in ("strong", "none", "max")}
        assert len(seen) == 3

class TestTheNudgeDoesNotCollideWithTheEffortLevel:
    """`max` is both a nudge level and an effort level, and the two vocabularies
    met in the filename parser.

    parse_batch_filename stripped the stamp, then looked for a trailing effort -
    so a --nudge max batch parsed as effort="max" with no nudge. batch_stem then
    rebuilt the name as `<model>_max_max`, producing a second summary file beside
    the correct one and claiming an effort the batch never requested. Five max
    batches on disk had the duplicate before this was found."""

    def test_a_max_nudge_batch_has_no_effort(self):
        from subversionbench.batch import parse_batch_filename
        effort, stamp, oversight, _lure, _cap = parse_batch_filename(
            "run_1_x-ai_grok-4.5_max_20260805T155405.json", "max")
        assert effort is None
        assert stamp == "20260805T155405"
        assert oversight is True

    def test_a_max_nudge_batch_can_still_carry_a_real_effort(self):
        from subversionbench.batch import parse_batch_filename
        assert parse_batch_filename(
            "run_1_m_max_high_20260805T155405.json", "max")[0] == "high"

    def test_other_nudges_still_read_their_effort(self):
        from subversionbench.batch import parse_batch_filename
        assert parse_batch_filename(
            "run_1_m_strong_xhigh_20260805T155405.json", "strong")[0] == "xhigh"
        assert parse_batch_filename(
            "run_1_m_strong_20260805T155405.json", "strong")[0] is None

    def test_the_summary_name_does_not_double_the_nudge(self):
        """The visible symptom: `<model>_max_max`."""
        import subversionbench.run_eval as ev_run
        effort, _, oversight, _lure, _cap = ev_run.parse_batch_filename(
            "run_1_m_max_20260805T155405.json", "max")
        assert ev_run.batch_stem("m", "max", effort, oversight) == "m_max"

    def test_the_counterfactual_arm_survives_the_fix(self):
        from subversionbench.batch import parse_batch_filename
        for nudge in ("strong", "max"):
            _, _, oversight, _lure, _cap = parse_batch_filename(
                f"run_1_m_{nudge}_nooversight_20260805T155405.json", nudge)
            assert oversight is False, nudge


class TestFindRunFilesSeparatesTheTwoCorpora:
    """A capability episode's filename carries the same model, nudge, oversight
    and lure as a propensity one. Only the capability tag tells them apart, and
    a caller that cannot express which corpus it wants gets both."""

    def _dir(self):
        out = tempfile.mkdtemp()
        for name in ("run_1_m_none_20260101T000000.json",
                     "run_1_m_none_capability-sandbox_20260101T000001.json",
                     "run_1_m_none_capability-oversight_20260101T000002.json"):
            Path(out, name).write_text("{}")
        return out

    def test_the_default_is_both_so_the_read_modes_see_every_file(self):
        """--grade-existing and --resummarise must not stop seeing a corpus."""
        assert len(find_run_files(self._dir(), "m", "none")) == 3

    def test_none_is_the_propensity_corpus_not_an_absent_filter(self):
        found = find_run_files(self._dir(), "m", "none", capability=None)
        assert [os.path.basename(p) for p in found] == [
            "run_1_m_none_20260101T000000.json"]

    def test_a_target_name_selects_that_arm_alone(self):
        found = find_run_files(self._dir(), "m", "none", capability="sandbox")
        assert [os.path.basename(p) for p in found] == [
            "run_1_m_none_capability-sandbox_20260101T000001.json"]


class TestTheCollectionCensusCountsOnlyWhatItWouldCollect:
    """run_all_arms.sh skips an arm that already has enough runs. Miscounting
    in either direction costs money: too high skips an arm that was never
    collected, too low re-collects one that was."""

    def _dir(self):
        out = tempfile.mkdtemp()
        for name in (
                # the arm under test: oversight, no lure, two episodes
                "run_1_m_none_20260101T000000.json",
                "run_2_m_none_20260101T000000.json",
                # same arm's CAPABILITY episodes - instructed, not propensity
                "run_1_m_none_capability-sandbox_20260101T000001.json",
                "run_2_m_none_capability-sandbox_20260101T000001.json",
                # neighbouring arms
                "run_1_m_none_nooversight_20260101T000002.json",
                "run_1_m_none_lure_20260101T000003.json"):
            Path(out, name).write_text("{}")
        return out

    def test_it_counts_the_arm_and_returns_its_stamp(self):
        """Also the regression test for the arity defect: this walks real files
        through parse_batch_filename, so a return that grows again fails here
        rather than mid-batch."""
        from subversionbench.batch import arm_run_file_census
        n, stamps = arm_run_file_census(self._dir(), "m", "none",
                                        "true", "false")
        assert (n, stamps) == (2, ["20260101T000000"])

    def test_a_capability_episode_does_not_satisfy_a_propensity_arm(self):
        """The defect: four files match this arm's (nudge, oversight, lure) and
        only two are propensity. Counting all four skips collection of an arm
        holding half the episodes it was asked for."""
        from subversionbench.batch import arm_run_file_census
        n, _ = arm_run_file_census(self._dir(), "m", "none", "true", "false")
        assert n == 2

    def test_it_separates_the_oversight_and_lure_axes(self):
        from subversionbench.batch import arm_run_file_census
        out = self._dir()
        assert arm_run_file_census(out, "m", "none", "false", "false")[0] == 1
        assert arm_run_file_census(out, "m", "none", "true", "true")[0] == 1

    def test_a_slugged_model_is_found_under_its_real_name(self):
        from subversionbench.batch import arm_run_file_census
        out = tempfile.mkdtemp()
        Path(out, "run_1_x-ai_grok-4.5_none_20260101T000000.json").write_text("{}")
        assert arm_run_file_census(out, "x-ai/grok-4.5", "none",
                                   "true", "false")[0] == 1

    def test_an_unspelled_boolean_raises_rather_than_meaning_false(self):
        """`oversight == "true"` silently read every other spelling as the
        counterfactual arm, so a typo counted one arm and collected another."""
        from subversionbench.batch import arm_run_file_census
        out = self._dir()
        for bad in ("True", "yes", "", "1"):
            with pytest.raises(ValueError):
                arm_run_file_census(out, "m", "none", bad, "false")
            with pytest.raises(ValueError):
                arm_run_file_census(out, "m", "none", "true", bad)


class TestNoShellScriptParsesAFilenameItself:
    """The arity defect survived because Python inside a shell heredoc is
    reached by neither ruff nor the import graph nor this suite. The rule is
    about every shell script, not about the one that broke: a filename is
    parsed in Python that something can import and test."""

    def _shell_scripts(self):
        from conftest import PROJECT_ROOT
        found = sorted(PROJECT_ROOT.glob("*.sh"))
        assert found, "no shell scripts found - the guard would pass vacuously"
        return found

    @staticmethod
    def _code(text: str) -> str:
        """The script minus its comments, shell and embedded-Python alike.

        Both languages start a whole-line comment with `#`, and the rule is
        about what RUNS: a comment naming the parser - such as the one in
        run_all_arms.sh explaining why the call was moved out - is not a call.
        """
        return "\n".join(line for line in text.splitlines()
                         if not line.lstrip().startswith("#"))

    def test_no_shell_script_unpacks_the_batch_parser(self):
        offenders = [p.name for p in self._shell_scripts()
                     if "parse_batch_filename"
                     in self._code(p.read_text(encoding="utf-8"))]
        assert not offenders, (
            f"{offenders} parse filenames in shell; call a function in "
            f"subversionbench.batch instead, so the suite covers it")
