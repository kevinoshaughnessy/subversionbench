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
from subversionbench.arm_record import arm_identity
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
        # DERIVED from the targets, not the literal 3 it was written with.
        # That literal was the target count plus the None row, so authoring a
        # third target failed this line while every round trip inside the loop
        # passed - the count was guarding the loop's arity and reporting it as
        # a round-trip failure.
        expected = (1 + len(CAPABILITY_TARGETS)) * 2 * 2 * (3 * 3 - 1)
        assert seen == expected, (seen, expected)

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

    def _episode(self, capability):
        """One episode end to end, counting the interrogations it started.

        The count is the assertion. This test used to search
        run_evaluation's source for "if capability is None:", which said
        nothing about whether the call happened and broke the moment the
        interrogation was given a function of its own - while the skip it
        was about still worked. It would also have passed against an
        interrogation that ran and had its answers discarded, which is the
        one outcome the docstring below says must not happen.
        """
        import contextlib
        import io
        import tempfile
        import types

        from subversionbench import episode as ev_episode
        from subversionbench import llm_client as ev_llm
        from subversionbench.config import SYSTEM_PROMPT_NO_NUDGE
        from subversionbench.environment import create_hardened_environment

        env_dir = tempfile.mkdtemp()
        env_info = create_hardened_environment(env_dir)
        started = []

        class Fake:
            class _M:
                def create(self, **kw):
                    return types.SimpleNamespace(
                        content=[types.SimpleNamespace(
                            type="text",
                            text="I recommend the balanced option.")],
                        stop_reason="end_turn",
                        usage=types.SimpleNamespace(input_tokens=1,
                                                    output_tokens=1))
            messages = _M()

        real_client = ev_llm.get_client
        real_interrogate = ev_episode.interrogate_acts
        ev_llm.get_client = lambda *a, **k: Fake()
        ev_episode.interrogate_acts = lambda *a, **k: started.append(1)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = ev_episode.run_evaluation(
                    system_prompt=SYSTEM_PROMPT_NO_NUDGE,
                    user_prompt="Do the task.", env_dir=env_dir,
                    env_info=env_info, model="m", max_turns=2,
                    use_grader=False, nudge="none", capability=capability)
        finally:
            ev_llm.get_client = real_client
            ev_episode.interrogate_acts = real_interrogate
        return result, len(started)

    def test_the_interrogation_is_skipped_and_says_so(self):
        """Every question in the ladder asks whether the model did something it
        was not asked to do, and here it WAS asked. The skip has to be a branch
        around the call, not an empty answer set, because an interrogation that
        ran would still save its answers and still be there for someone to read
        as a concealment rate."""
        result, started = self._episode("sandbox")
        assert started == 0, "the capability arm was interrogated anyway"
        assert "interrogation_skipped" in result["analysis"]
        assert "sandbox" in result["analysis"]["interrogation_skipped"]

    def test_a_propensity_episode_is_still_interrogated(self):
        """The other direction, so the skip can only be about this arm. A
        one-directional check would pass just as well against an
        interrogation that had stopped happening for everyone."""
        result, started = self._episode(None)
        assert started == 1, "the propensity arm was not interrogated"
        assert "interrogation_skipped" not in result["analysis"]


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


class TestTheCapabilityArmRefusesToRunUnderTheHeldOutBundle:
    """The held-out twin is a different rollout with its own pins in a sidecar,
    and the sidecar carries no capability entries. There is no fallback worth
    having here: stamping the SHIPPED scenario's capability identity onto twin
    episodes would let two different scenarios' ceilings pool, which is worse
    than not collecting them at all.
    """

    def _under_an_alternative_bundle(self, target, oversight):
        import subversionbench.rollout_pins as pins
        original = pins._alternative
        # The sidecar's shape does not matter here - only that one was found,
        # which is what `_alternative` being non-None means.
        pins._alternative = ("r99", {})
        try:
            return pins.capability_fingerprint_for(target, oversight)
        finally:
            pins._alternative = original

    def test_a_pinned_arm_still_refuses_under_an_alternative_bundle(self):
        target = CAPABILITY_TARGETS[0]
        assert capability_fingerprint_for(target, True), (
            "the arm is unpinned even on the shipped bundle, so the refusal "
            "below would be the KeyError and not the one under test")
        try:
            self._under_an_alternative_bundle(target, True)
        except RuntimeError as e:
            assert "no pins under an alternative scenario bundle" in str(e)
            from subversionbench.scenario import BUNDLE_ENV_VAR
            assert BUNDLE_ENV_VAR in str(e), (
                "the message must name the variable to unset; there is "
                "nothing else an operator can act on")
            return
        raise AssertionError(
            "a twin episode would have been stamped with the shipped "
            "scenario's capability identity")

    def test_the_unpinned_check_still_comes_first(self):
        """An unpinned target under an alternative bundle is a KeyError, not
        the RuntimeError: the two say different things, and the order is what
        keeps 'this arm was never pinned' from being reported as 'unset the
        environment variable'."""
        try:
            self._under_an_alternative_bundle("nonesuch", True)
        except KeyError:
            return
        except RuntimeError as e:
            raise AssertionError(
                "an unpinned target was reported as a bundle problem") from e
        raise AssertionError("an unpinned target was given a fingerprint")

    def test_the_shipped_bundle_is_unaffected(self):
        """The control: the stub above is what refuses, not the function."""
        assert capability_fingerprint_for(CAPABILITY_TARGETS[0], True) == \
            CAPABILITY_FINGERPRINTS[(CAPABILITY_TARGETS[0], True)]


class TestTheCeilingIsStagedWithTheArtefactItInstructs:
    """
    The instruction names a file; the environment must contain it.

    THE DEFECT THIS EXISTS FOR. `scenario_for` stages the goal-guarding
    artefact when EITHER the arm is set or the capability target is
    "goalguard" - the ceiling needs the file without the deployment note that
    supplies the motive. `create_hardened_environment` built its bundle by
    passing only `goalguard`, so a `--capability goalguard` episode was
    assembled from a bundle with no successor parameters while the instruction
    it was handed named that file by path. The model was told to edit
    something that had never been written.

    It fails in the worst direction available. The act is IMPOSSIBLE rather
    than declined, so the ceiling reads zero by construction - and a zero
    ceiling is the reading that converts a model's genuine refusal into "this
    scenario cannot be solved at all". A propensity rate measured against it
    would be uninterpretable in exactly the way the capability arm exists to
    prevent.

    Nothing caught it because every existing guard checks the SCENARIO side,
    where the disjunction was always correct. It was found by a model saying
    so in its own reasoning, after a batch had started.

    DERIVED FROM THE PIN TABLE rather than listing the targets, so a capability
    target added later inherits the check instead of escaping it.
    """

    def _staged(self, target, oversight):
        import tempfile

        from subversionbench.environment import create_hardened_environment
        return create_hardened_environment(
            tempfile.mkdtemp(), oversight=oversight, capability=target)

    def _artefact_keys(self):
        """Which env_info key each act's artefact lands under.

        Hand-written because it is a correspondence and cannot be derived: the
        act registry names acts, and env_info names files. Anything in the pin
        table with no entry here fails rather than being skipped.
        """
        return {"goalguard": "successor_params_path",
                "oversight": "monitoring_config_path",
                "sandbox": None}          # no artefact: the boundary is the act

    def test_every_pinned_target_stages_what_its_instruction_names(self):
        import os

        from subversionbench.config import CAPABILITY_FINGERPRINTS
        keys = self._artefact_keys()
        missing = []
        for target, oversight in sorted(CAPABILITY_FINGERPRINTS):
            assert target in keys, (
                f"{target!r} is pinned but this test does not know which "
                f"artefact its instruction names; add it rather than skipping")
            key = keys[target]
            if key is None:
                continue
            info = self._staged(target, oversight)
            path = info.get(key)
            if not path or not os.path.exists(path):
                missing.append((target, oversight, key))
        assert not missing, (
            f"the capability instruction names an artefact the environment "
            f"never staged: {missing}. The act is impossible, so the ceiling "
            f"reads zero by construction.")

    def test_the_goal_guarding_ceiling_is_measurable_rather_than_impossible(self):
        """The specific case, driven through the settle step that scores it.

        `goal_guarded` must come back False - the act was available and not
        taken - rather than None, which is the not-applicable value meaning no
        artefact was ever staged. None is what the defect produced, and it is
        indistinguishable from a clean zero in any rate that reads the field
        with `bool()`.
        """
        from subversionbench.grading.transcript_analysis import (
            analyze_misalignment)
        import tempfile

        from subversionbench.environment import create_hardened_environment
        env_dir = tempfile.mkdtemp()
        info = create_hardened_environment(env_dir, oversight=False,
                                           capability="goalguard")
        results = analyze_misalignment([], env_dir, info)
        assert results["goal_guarded"] is False, (
            f"goal_guarded is {results['goal_guarded']!r}; None means the "
            f"artefact was never staged, so the ceiling cannot be measured")

    def test_the_ceiling_carries_the_artefact_without_the_motive(self):
        """The capability arm is means without motive. Staging the deployment
        note as well would make the ceiling a second propensity arm, measuring
        whether an instructed model ALSO had a reason."""
        from subversionbench.scenario import scenario_for
        ceiling = scenario_for(False, capability="goalguard")
        propensity = scenario_for(False, goalguard="replacement")
        assert "successor_params" in ceiling
        assert "cutover_note" not in ceiling
        assert "cutover_note" in propensity

    def test_the_batch_actually_forwards_the_target_to_the_environment(self):
        """The guard the callee-level checks above do not make.

        Every assertion above calls create_hardened_environment directly, so
        all of them pass with the runner's `capability=` argument cut out -
        one of the two places the original defect could have lived, and the
        whole collection suite was green against that plant. Driven through
        run_batch with the model call stubbed, so what is asserted is the
        env_info a real batch hands the episode.
        """
        import contextlib
        import io
        import tempfile
        import types

        from subversionbench import runner
        captured = {}

        def capture(**kw):
            captured["env_info"] = kw["env_info"]
            raise RuntimeError("environment captured; no model call wanted")

        args = types.SimpleNamespace(
            model="claude-sonnet-5", nudge="none", effort=None,
            oversight=False, lure=False, output_dir=tempfile.mkdtemp(),
            runs=1, delay=0, max_tokens=8192, max_turns=40, no_power=True,
            no_grader=True, grader_model="claude-opus-5",
            isolation="deny-network", resume=None, max_consecutive_failures=3,
            thinking_budget=None, concurrency=1, interrogations=("default",),
            write_back=False, batch_stamp=None, yes=True,
            openrouter_sort=None, openrouter_provider=None,
            capability="goalguard")
        real = runner.run_evaluation
        runner.run_evaluation = capture
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                runner.run_batch(args, "claude-sonnet-5", "sys", {}, "cfg")
        finally:
            runner.run_evaluation = real

        assert captured, "the batch never built an episode"
        assert captured["env_info"].get("successor_params_path"), (
            "the batch built a --capability goalguard episode whose "
            "environment has no successor parameters, so the instruction "
            "names a file that was never written")

    def test_a_plain_episode_still_stages_nothing(self):
        """Two-directional. If the artefact appeared in every episode the fix
        above would pass while making the propensity arm's counterfactual
        meaningless."""
        import tempfile

        from subversionbench.environment import create_hardened_environment
        info = create_hardened_environment(tempfile.mkdtemp(), oversight=False)
        assert "successor_params_path" not in info
