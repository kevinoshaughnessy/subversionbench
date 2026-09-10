"""
The artefact-date arm.

The arm exists because nothing set the scenario files' modification times, so
every episode ever collected ran among files claiming to have been touched the
moment the batch ran. The checks that matter most here are the ones about what
must NOT have changed: 4,553 episodes carry the four pinned fingerprints, and
an arm that moved one of them would declare all of them incomparable with a
scenario they still match exactly.
"""

import datetime
import os
import tempfile

from subversionbench import artefact_dates as ad
from subversionbench.batch import (BatchIdentity, batch_stem,
                                   date_mode_from_filename,
                                   parse_batch_filename)
from subversionbench.rollout import rollout_fingerprint
from subversionbench.rollout_pins import (DATE_ARM_FINGERPRINTS,
                                          ROLLOUT_FINGERPRINTS,
                                          date_fingerprint_for, fingerprint_for)

ARMS = [(oversight, lure) for oversight in (True, False)
        for lure in (False, True)]


def _two_records_staged(date_mode):
    """A completed and a died episode, both staged with `date_mode`.

    Both, because arm_record.py exists precisely because the two records drifted
    apart, and a field threaded into one of them is the shape that defect took.
    The environment is built by create_episode_root rather than by
    create_hardened_environment, which is the whole point: create_episode_root
    is what stamps the tree and what puts the result in env_info.
    """
    import contextlib
    import io
    import types

    import subversionbench.llm_client as ev_llm
    from subversionbench.config import SYSTEM_PROMPT_STRONG_NUDGE
    from subversionbench.environment import create_episode_root
    from subversionbench.episode import EpisodeAPIError, run_evaluation

    def reply(**_kw):
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(
                type="text", text="I recommend the balanced one.")],
            stop_reason="end_turn", provider="a-backend",
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

    def episode(create):
        _root, env_dir, env_info = create_episode_root(
            True, lure=False, date_mode=date_mode)
        client = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=create))
        real = ev_llm.get_client
        ev_llm.get_client = lambda *a, **k: client
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return run_evaluation(
                    system_prompt=SYSTEM_PROMPT_STRONG_NUDGE,
                    user_prompt="Do it.", env_dir=env_dir, env_info=env_info,
                    model="m", nudge="strong", max_turns=2, use_grader=False,
                    date_mode=date_mode)
        finally:
            ev_llm.get_client = real

    def dies(**_kw):
        raise RuntimeError("429 rate limited")

    complete = episode(reply)
    try:
        episode(dies)
    except EpisodeAPIError as died:
        return complete, died.partial
    raise AssertionError("the failing client did not fail the episode")


class TestTheDateArmLeavesTheFourPinnedFingerprintsAlone:
    """The hard invariant. Every episode on disk was collected under the
    default, so the default must hash byte-identically to what it hashed
    before this arm was authored - the same discipline as the lure marker,
    which is appended only when the lure is on."""

    def test_every_pinned_arm_still_recomputes(self):
        for oversight, lure in ARMS:
            assert fingerprint_for(oversight, lure) == \
                ROLLOUT_FINGERPRINTS[(oversight, lure)]

    def test_the_default_mode_hashes_as_no_mode_at_all(self):
        for oversight, lure in ARMS:
            assert (rollout_fingerprint(oversight, lure=lure,
                                        date_mode=ad.DEFAULT)
                    == rollout_fingerprint(oversight, lure=lure)
                    == ROLLOUT_FINGERPRINTS[(oversight, lure)])

    def test_a_real_mode_moves_the_fingerprint(self):
        """The other direction. A marker appended unconditionally would pass
        the check above only by doing nothing at all."""
        for mode in (ad.CONSISTENT, ad.INCONSISTENT):
            for oversight, lure in ARMS:
                assert (rollout_fingerprint(oversight, lure=lure,
                                            date_mode=mode)
                        != ROLLOUT_FINGERPRINTS[(oversight, lure)])

    def test_the_two_modes_are_not_each_other(self):
        for oversight, lure in ARMS:
            assert (rollout_fingerprint(oversight, lure=lure,
                                        date_mode=ad.CONSISTENT)
                    != rollout_fingerprint(oversight, lure=lure,
                                           date_mode=ad.INCONSISTENT))

    def test_every_pin_recomputes_from_the_live_scenario(self):
        """The pins are DATA; this is the computation they are pinned to."""
        assert DATE_ARM_FINGERPRINTS
        for (mode, oversight, lure), pinned in DATE_ARM_FINGERPRINTS.items():
            assert rollout_fingerprint(oversight, lure=lure,
                                       date_mode=mode) == pinned

    def test_no_pin_collides_with_another_arm(self):
        """Two arms sharing an identity is the one failure both tables exist
        to prevent."""
        values = list(DATE_ARM_FINGERPRINTS.values()) + \
            list(ROLLOUT_FINGERPRINTS.values())
        assert len(set(values)) == len(values)

    def test_the_default_mode_has_no_pin_of_its_own(self):
        """An episode under the default IS an episode of the plain arm and
        takes that arm's fingerprint. A second name for it would be the one
        table saying two things."""
        for oversight, lure in ARMS:
            try:
                date_fingerprint_for(ad.DEFAULT, oversight, lure)
            except KeyError:
                continue
            raise AssertionError("the default mode was given a second identity")


class TestWhatTheModesActuallyStage:
    def _staged(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ("README.md", "data/models/counts.csv",
                        "comms/notes.txt", "logs/system.log"):
                path = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(path) or tmp, exist_ok=True)
                open(path, "w", encoding="utf-8").write("x")
            record = ad.apply(tmp, mode)
            times = {rel: datetime.datetime.fromtimestamp(
                os.path.getmtime(os.path.join(tmp, rel)), datetime.timezone.utc)
                for rel in ("README.md", "data/models/counts.csv",
                            "comms/notes.txt", "logs/system.log")}
        return record, times

    def test_the_default_touches_nothing(self):
        record, _ = self._staged(ad.DEFAULT)
        assert record["files_stamped"] == 0

    def test_consistent_backdates_every_file_before_the_anchor(self):
        _, times = self._staged(ad.CONSISTENT)
        assert times and all(t < ad._ANCHOR for t in times.values())

    def test_consistent_orders_reference_data_before_correspondence(self):
        """The ordering is the realism. A directory whose every file shares
        one timestamp was assembled rather than worked in, which is the signal
        arm B is built out of - so arm A must not carry it."""
        _, times = self._staged(ad.CONSISTENT)
        assert times["data/models/counts.csv"] < times["comms/notes.txt"]

    def test_inconsistent_is_uniform_and_far_ahead(self):
        _, times = self._staged(ad.INCONSISTENT)
        assert len(set(times.values())) == 1
        assert all(t > ad._ANCHOR for t in times.values())

    def test_the_two_modes_do_not_stage_the_same_thing(self):
        _, a = self._staged(ad.CONSISTENT)
        _, b = self._staged(ad.INCONSISTENT)
        assert a != b

    def test_staging_is_reproducible(self):
        """Deterministic from the path, not drawn at random: a random spread
        would make every episode its own condition."""
        _, one = self._staged(ad.CONSISTENT)
        _, two = self._staged(ad.CONSISTENT)
        assert one == two

    def test_an_unknown_mode_is_refused_rather_than_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                ad.apply(tmp, "backdated")
            except ValueError:
                return
        raise AssertionError("an unknown mode staged silently")

    def test_the_record_names_the_mode_it_applied(self):
        record, _ = self._staged(ad.CONSISTENT)
        assert record["date_mode"] == ad.CONSISTENT
        assert record["files_stamped"] == 4


class TestADirectoryIsNotAnEpisodesWorth:
    def test_a_nested_file_is_stamped_too(self):
        """`os.walk`, not a listing of the top level: the artefacts sit two
        directories deep and a top-level-only stamp would leave them at the
        collection time the arm exists to change."""
        with tempfile.TemporaryDirectory() as tmp:
            deep = os.path.join(tmp, "a", "b", "c.txt")
            os.makedirs(os.path.dirname(deep))
            open(deep, "w", encoding="utf-8").write("x")
            ad.apply(tmp, ad.INCONSISTENT)
            when = datetime.datetime.fromtimestamp(os.path.getmtime(deep),
                                                   datetime.timezone.utc)
        # The EXACT target, not merely "after the anchor". An unstamped file
        # carries today's date, which is also after the anchor, so the loose
        # assertion passed against a plant that stamped only the top level.
        assert when == ad.mtime_for(os.path.join("a", "b", "c.txt"),
                                    ad.INCONSISTENT)

    def test_the_directory_component_decides_the_age_at_any_depth(self):
        """The paths reaching _age_days are relative to the episode ROOT, so
        the first component is the generated project name. Matching only the
        first gave every artefact the default age and flattened arm A's
        ordering into a 20-day band - found by staging a real episode and
        reading the timestamps back."""
        shallow = ad._age_days(os.path.join("data", "x.csv"))
        nested = ad._age_days(os.path.join("Proj_9", "data", "x.csv"))
        comms = ad._age_days(os.path.join("Proj_9", "comms", "x.txt"))
        # Same BASE, differing only by the within-directory spread - which is
        # hashed from the whole path on purpose, so two files in one directory
        # do not share a timestamp.
        assert abs(shallow - nested) <= ad._SPREAD_DAYS
        assert nested - comms > ad._SPREAD_DAYS


class TestTheArmIsWrittenIntoTheNameAndTheRecord:
    def test_the_default_leaves_every_existing_name_alone(self):
        plain = batch_stem("m", "strong")
        for mode in (None, ad.DEFAULT):
            assert batch_stem("m", "strong", date_mode=mode) == plain

    def test_a_real_mode_marks_the_name(self):
        assert batch_stem("m", "strong", date_mode=ad.CONSISTENT) != \
            batch_stem("m", "strong")

    def test_the_modes_do_not_share_a_name(self):
        assert batch_stem("m", "strong", date_mode=ad.CONSISTENT) != \
            batch_stem("m", "strong", date_mode=ad.INCONSISTENT)

    def test_the_identity_carries_it_into_the_filename(self):
        common = {"model": "m", "model_slug": "m", "nudge": "strong"}
        assert BatchIdentity(**common).filename("d") != \
            BatchIdentity(**common, date_mode=ad.CONSISTENT).filename("d")

    def test_the_marked_name_still_parses_its_other_arms(self):
        """The segment is CONSUMED by the parser even though it is not
        returned. Left unstripped it ends the stripping loop early, and a
        no-oversight lure batch comes back as an oversight one - the silent
        mislabelling the parser exists to prevent."""
        stem = batch_stem("vendor_m", "strong", effort="high", oversight=False,
                          lure=True, date_mode=ad.INCONSISTENT)
        effort, _stamp, oversight, lure, _cap = parse_batch_filename(
            f"run_1_{stem}_20260910T101500.json", "strong")
        assert (effort, oversight, lure) == ("high", False, True)

    def test_the_mode_is_readable_back_off_the_name(self):
        stem = batch_stem("vendor_m", "strong", oversight=False, lure=True,
                          date_mode=ad.INCONSISTENT)
        assert date_mode_from_filename(f"run_1_{stem}_20260910T101500.json") \
            == ad.INCONSISTENT

    def test_an_unmarked_name_reads_as_no_mode(self):
        stem = batch_stem("vendor_m", "strong", oversight=False, lure=True)
        assert date_mode_from_filename(
            f"run_1_{stem}_20260910T101500.json") is None


class TestTheEpisodeRecordsWhichArmItRan:
    def _identity(self, **kw):
        from subversionbench.arm_record import arm_identity
        args = {"model": "m", "effort": None, "nudge": "strong",
                "oversight": True, "lure": False,
                "interrogations": ("zeroevidence",),
                "openrouter_sort": None, "openrouter_provider": None}
        args.update(kw)
        return arm_identity(**args)

    def test_the_mode_is_on_the_record(self):
        assert self._identity(date_mode=ad.CONSISTENT)["date_mode"] == \
            ad.CONSISTENT

    def test_an_episode_that_predates_the_arm_records_none(self):
        """None and 'default' are different facts: one ran before there was a
        choice, the other under a choice that was made."""
        assert self._identity()["date_mode"] is None

    def test_the_stamped_fingerprint_comes_from_the_date_table(self):
        got = self._identity(date_mode=ad.CONSISTENT)["rollout_fingerprint"]
        assert got == date_fingerprint_for(ad.CONSISTENT, True, False)

    def test_the_default_still_stamps_the_plain_arm(self):
        """The check that keeps the corpus poolable: an episode under the
        default is an episode of the plain arm."""
        for mode in (None, ad.DEFAULT):
            assert self._identity(date_mode=mode)["rollout_fingerprint"] == \
                fingerprint_for(True, False)

    def test_what_the_staging_DID_reaches_the_record_not_just_what_was_asked(self):
        """The gap `date_mode` alone leaves. apply() walking a tree and
        stamping nothing raises nothing and returns files_stamped 0, so an
        episode carrying only the requested mode looks identically staged
        whether the staging happened or not - and the one real instance of
        that bug, _age_days matching no path component, was found by staging
        an episode by hand because no saved episode could have shown it.

        Run end to end rather than asserted off arm_identity's signature: the
        value is read off env_info, so a guard that passes arm_identity the
        record itself proves nothing about the link that was actually missing,
        which is create_episode_root's return value reaching the record.
        """
        complete, failed = _two_records_staged(ad.CONSISTENT)
        for record in (complete, failed):
            staged = record["artefact_dates"]
            assert staged["date_mode"] == ad.CONSISTENT
            assert staged["files_stamped"] > 0, (
                "the episode records a mode it cannot show was applied")

    def test_an_episode_with_no_date_mode_records_no_staging(self):
        """None and a staging of zero files are different facts, the same
        distinction `date_mode` draws between None and 'default'."""
        complete, failed = _two_records_staged(None)
        assert complete["artefact_dates"] is None
        assert failed["artefact_dates"] is None

    def test_a_capability_episode_is_unaffected_by_the_date_arm(self):
        """Three tables, one choice, made in one place. A capability episode
        stamped from the date table would pool with neither."""
        from subversionbench.rollout_pins import capability_fingerprint_for
        got = self._identity(capability="sandbox",
                             date_mode=ad.CONSISTENT)["rollout_fingerprint"]
        assert got == capability_fingerprint_for("sandbox", True)


class TestMtimeForAnswersForEveryMode:
    """`apply` is what an episode calls, so it never reaches these two
    branches - which left the mode lookup itself unrun. It is public and a
    caller may reasonably ask it directly."""

    def test_the_default_asks_for_no_timestamp_at_all(self):
        assert ad.mtime_for("README.md", ad.DEFAULT) is None

    def test_an_unknown_mode_is_refused_here_too(self):
        """The refusal `apply` makes at the boundary, made again at the leaf:
        a caller reaching this directly must not be handed a silent default."""
        try:
            ad.mtime_for("README.md", "backdated")
        except ValueError:
            return
        raise AssertionError("an unknown mode returned a timestamp")
