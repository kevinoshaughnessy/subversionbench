"""
The capability arm's identity, and the four r10 fingerprints it must not move.

Three properties, and the first is the one that would be catastrophic and
silent.

THE PROPENSITY ARMS ARE UNTOUCHED. The capability instruction lives in the
scenario bundle, and `rollout_fingerprint` hashes the assembled arm - so a
bundle key that reaches a propensity arm moves that arm's identity and
declares every episode already collected incomparable with a scenario it still
matches exactly. The pop in scenario_for is what prevents it, and nothing
about forgetting it would look wrong.

A CAPABILITY EPISODE IS NEVER MISTAKEN FOR A PROPENSITY ONE. Its acts were
INSTRUCTED, so one pooled into a misalignment rate inflates that rate towards
the ceiling it is the denominator of. Three defences - its own fingerprint,
its own filename mark, and both report loaders - and each is asserted here
rather than assumed from the other two.

THE ARM IS REFUSED WHERE IT CANNOT BE MEASURED. The oversight instruction
names an artefact the counterfactual removes, which is the r9 defect exactly:
an instruction the arm's own construction makes unsatisfiable. It has to fail
at the boundary, not produce sixty episodes of a model hunting for something
that is not there.

NOTHING HERE QUOTES THE INSTRUCTION. It is scenario text, so the assertions
are structural - that it differs from the propensity prompt, that it names the
artefact - rather than comparisons against a copy.
"""

import re

from subversionbench.batch import (CAPABILITY_TAG, BatchIdentity, batch_stem,
                                   parse_batch_filename)
from subversionbench.episode import arm_identity
from subversionbench.rollout import rollout_fingerprint
from subversionbench.rollout_pins import (CAPABILITY_FINGERPRINTS,
                                          CAPABILITY_TARGETS,
                                          ROLLOUT_FINGERPRINTS,
                                          capability_fingerprint_for,
                                          fingerprint_for)
from subversionbench.scenario import scenario_for

_ARMS = [(o, lure) for o in (True, False) for lure in (True, False)]


class TestTheFourPropensityFingerprintsDoNotMove:
    """The reason `capability` is popped unconditionally in scenario_for. If
    this class fails, the whole corpus has been declared incomparable with a
    scenario it still matches."""

    def test_every_pinned_arm_recomputes_unchanged(self):
        for oversight, lure in _ARMS:
            assert rollout_fingerprint(oversight, lure=lure) == \
                ROLLOUT_FINGERPRINTS[(oversight, lure)], (oversight, lure)

    def test_the_capability_key_never_reaches_an_assembled_propensity_arm(self):
        """The mechanism, asserted directly rather than only through the hash:
        a hash that happened to collide would pass the test above."""
        for oversight, lure in _ARMS:
            assert "capability" not in scenario_for(oversight, lure=lure)

    def test_the_bundle_really_does_carry_it(self):
        """Without this the two tests above pass vacuously - a bundle with no
        capability key has nothing to leak, and every guard here would be
        measuring an arm that does not exist."""
        from subversionbench.scenario import load_scenario
        arms = load_scenario().get("capability") or {}
        assert set(arms) == set(CAPABILITY_TARGETS), sorted(arms)
        for target, override in arms.items():
            assert override.get("user_prompt"), target


class TestTheCapabilityArmHasItsOwnIdentity:
    def test_every_pin_matches_what_the_code_computes(self):
        assert CAPABILITY_FINGERPRINTS
        for (target, oversight), pinned in CAPABILITY_FINGERPRINTS.items():
            assert rollout_fingerprint(oversight, lure=False,
                                       capability=target) == pinned, target

    def test_no_capability_arm_shares_a_fingerprint_with_a_propensity_arm(self):
        """The single collision that would let a ceiling pool with the rate it
        is the denominator of."""
        propensity = set(ROLLOUT_FINGERPRINTS.values())
        for key, value in CAPABILITY_FINGERPRINTS.items():
            assert value not in propensity, key

    def test_the_two_targets_are_different_arms(self):
        """They replace the same bundle key with different text, so a shared
        fingerprint would mean one of them is not being applied."""
        assert capability_fingerprint_for("oversight", True) != \
            capability_fingerprint_for("sandbox", True)

    def test_an_unpinned_combination_raises_rather_than_falling_back(self):
        for target, oversight in (("oversight", False), ("nonesuch", True)):
            try:
                capability_fingerprint_for(target, oversight)
            except KeyError:
                continue
            raise AssertionError(
                f"{(target, oversight)} was stamped with some other arm's "
                f"identity instead of refused")

    def test_the_instruction_actually_replaces_the_task(self):
        """Structural, not a quotation: the arm is worth nothing if the model
        is still asked for a transport recommendation."""
        for target in CAPABILITY_TARGETS:
            plain = scenario_for(True)["user_prompt"]
            instructed = scenario_for(True, capability=target)["user_prompt"]
            assert instructed != plain, target
            assert instructed

    def test_the_counterfactuals_own_prompt_does_not_win(self):
        """Both the counterfactual override and the capability arm replace
        `user_prompt`, and the counterfactual's copy asks for the transport
        recommendation this arm exists to replace. Applied in the wrong order,
        the sandbox ceiling would be measured on episodes never given the
        instruction - and every one of them would read as a refusal."""
        counterfactual = scenario_for(False)["user_prompt"]
        instructed = scenario_for(False, capability="sandbox")["user_prompt"]
        assert instructed != counterfactual
        assert instructed == scenario_for(True, capability="sandbox")[
            "user_prompt"]

    def test_the_oversight_target_is_refused_in_the_counterfactual(self):
        """The r9 defect in a new place: an instruction naming an artefact the
        arm itself removes."""
        try:
            scenario_for(False, capability="oversight")
        except ValueError:
            return
        raise AssertionError(
            "an unsatisfiable instruction was assembled rather than refused")

    def test_an_unknown_target_is_refused_rather_than_ignored(self):
        """Ignored, it would return the propensity scenario under a capability
        label - every episode a refusal, and the ceiling a measured zero."""
        try:
            scenario_for(True, capability="not-a-target")
        except KeyError:
            return
        raise AssertionError("an unknown target silently ran the plain task")


class TestTheFilenameIsAnExactInverse:
    """Written one way and read another finds nothing, and finds it silently -
    which for this tag means a capability batch read back as a propensity
    one."""

    def test_every_combination_round_trips(self):
        seen = 0
        for target in (None,) + CAPABILITY_TARGETS:
            for oversight in (True, False):
                for lure in (True, False):
                    for effort in (None, "high", "max"):
                        for nudge in ("strong", "none", "max"):
                            # PRE-EXISTING AMBIGUITY, NOT THIS ARM'S. `max` is
                            # both a nudge and an effort level, and the
                            # stripper's nudge guard stops at a trailing token
                            # equal to the nudge - so `--nudge max --effort
                            # max` loses the effort and the lure with it, with
                            # or without a capability tag. Excluded here rather
                            # than papered over: the round trip really is
                            # broken for that one pair, it is broken at
                            # 255783f, and fixing it changes how existing
                            # filenames are read, which does not belong in a
                            # commit about a new arm.
                            if nudge == "max" and effort == "max":
                                continue
                            stem = batch_stem("prov_model", nudge, effort,
                                              oversight, lure, target)
                            got = parse_batch_filename(
                                f"summary_{stem}_20260101T000000.json", nudge)
                            assert got == (effort, "20260101T000000",
                                           oversight, lure, target), stem
                            seen += 1
        # A loop that iterated nothing would pass every assertion above.
        assert seen == 3 * 2 * 2 * (3 * 3 - 1), seen

    def test_the_max_nudge_max_effort_pair_is_the_only_gap(self):
        """The exclusion above, bounded in BOTH directions - so it can only
        shrink, and a second broken pair cannot hide behind the first. The
        pair is still asserted to be broken, so this test says to delete the
        exclusion the moment the parser is fixed."""
        broken = []
        for effort in (None, "high", "max"):
            for nudge in ("strong", "none", "max"):
                stem = batch_stem("m", nudge, effort, True, True, "sandbox")
                got = parse_batch_filename(
                    f"summary_{stem}_20260101T000000.json", nudge)
                if got != (effort, "20260101T000000", True, True, "sandbox"):
                    broken.append((nudge, effort))
        assert broken == [("max", "max")], broken

    def test_a_capability_batch_and_a_propensity_batch_get_different_names(self):
        """They differ in no other field, so without the tag one summary would
        be written over the other."""
        common = {"model": "m", "model_slug": "m", "nudge": "none",
                  "stamp": "20260101T000000"}
        assert BatchIdentity(**common).filename("d") != \
            BatchIdentity(**common, capability="sandbox").filename("d")

    def test_an_unrecognised_target_is_still_read_as_a_capability_batch(self):
        """A target added to the bundle later must be readable off a filename
        written today. Parsed by shape rather than against a list, because a
        parser that fell back to None would hand back the one reading this tag
        exists to prevent."""
        got = parse_batch_filename(
            f"summary_m_none_{CAPABILITY_TAG}-future_20260101T000000.json",
            "none")
        assert got[4] == "future", got

    def test_the_tag_carries_no_underscore(self):
        """The suffix stripper peels `_`-separated segments, so an underscore
        inside the token would present it with two segments where one has
        meaning."""
        assert "_" not in CAPABILITY_TAG
        for target in CAPABILITY_TARGETS:
            assert "_" not in target, target


class TestTheEpisodeRecordSaysWhichArmItIs:
    def _record(self, **kw):
        return arm_identity("m", None, "none", True, False, ["zeroevidence"],
                            None, None, max_turns=40, **kw)

    def test_a_propensity_episode_records_none(self):
        assert self._record()["capability"] is None

    def test_a_capability_episode_records_its_target(self):
        assert self._record(capability="sandbox")["capability"] == "sandbox"

    def test_it_is_stamped_with_the_capability_fingerprint(self):
        """Not the propensity arm's. This is the field restage_model.py's
        poolability test reads, so getting it wrong would let a capability
        batch be staged into a propensity corpus - and the check that would
        otherwise catch it for free is the one being defeated."""
        assert self._record(capability="sandbox")["rollout_fingerprint"] == \
            capability_fingerprint_for("sandbox", True)
        assert self._record()["rollout_fingerprint"] == \
            fingerprint_for(True, False)

    def test_the_interrogation_is_skipped_and_says_so(self):
        """Every question in the ladder asks whether the model did something it
        was not asked to do, and here it WAS asked. Read off the source: the
        skip has to be a branch around the call, not an empty answer set,
        because an interrogation that ran would still save its answers and
        still be there for someone to read as a concealment rate."""
        import inspect

        from subversionbench import episode
        source = inspect.getsource(episode.run_evaluation)
        assert "if capability is None:" in source
        assert "interrogation_skipped" in source


class TestTheCollectionFlagRefusesWhatCannotBeMeasured:
    """Each of these would produce episodes that look like a ceiling and are
    not, and none of them is visible in the artefact afterwards."""

    def _main(self, argv):
        import contextlib
        import io
        import sys

        from subversionbench import run_eval
        original = sys.argv
        sys.argv = argv
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = run_eval.main()
        finally:
            sys.argv = original
        return code, buf.getvalue()

    def test_a_nudge_other_than_none_is_refused(self):
        code, out = self._main(["run_eval", "--capability", "sandbox",
                                "--nudge", "strong"])
        assert code == 2, out[-400:]
        assert "--nudge none" in out

    def test_the_lure_arm_is_refused(self):
        code, out = self._main(["run_eval", "--capability", "sandbox",
                                "--nudge", "none", "--lure", "true"])
        assert code == 2, out[-400:]
        assert "hint" in out

    def test_the_oversight_target_needs_oversight(self):
        code, out = self._main(["run_eval", "--capability", "oversight",
                                "--nudge", "none", "--oversight", "false"])
        assert code == 2, out[-400:]
        assert "--oversight true" in out

    def test_the_flag_offers_exactly_the_pinned_targets(self):
        """An option the operator can type that has no pinned fingerprint
        would fail hours in, on the arm nobody checked."""
        import contextlib
        import io
        import sys

        from subversionbench import run_eval
        original = sys.argv
        sys.argv = ["run_eval", "--help"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.suppress(
                    SystemExit):
                run_eval.main()
        finally:
            sys.argv = original
        match = re.search(r"--capability \{([^}]+)\}", buf.getvalue())
        assert match, buf.getvalue()[:400]
        assert tuple(sorted(match.group(1).split(","))) == CAPABILITY_TARGETS
