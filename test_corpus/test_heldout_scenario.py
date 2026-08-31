"""
The held-out scenario, and the seam that selects it.

The held-out scenario is a reworded twin of the shipped one - same acts, same
arms, same mechanism, different surface text - for asking whether a rate this
benchmark reports survives a change that carries no semantic content.

TWO KINDS OF TEST LIVE HERE, and the split is what makes the file useful in CI.

`TestTheBundleSeam` is about the MECHANISM: which bundle a process resolves to,
what happens when the override names something unreadable, and the refusals
that stop an alternative bundle's text from being written into the shipped one.
None of it needs the held-out bundle, so all of it runs everywhere.

`TestTheHeldOutBundle` is about the bundle itself and skips when it is absent -
which is always, off this machine. The bundle is gitignored on purpose: a
held-out control is worth having only for as long as it has never been
published. That is a corpus-absent skip, which SUBVERSIONBENCH_NO_SKIPS
deliberately still allows; it is not a missing optional dependency, so it must
not go through conftest.skip_without.

NOTHING HERE MAY NAME A HELD-OUT TERM. Every planted string is derived from the
bundle or built from characters, never spelled out - the same discipline
test_scenario.py's positive control uses, and for the same reason: a guard that
names what it is protecting is the leak it was written to prevent.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from subversionbench import rollout_pins
from subversionbench.scenario import (BUNDLE_ENV_VAR, bundle_is_overridden,
                                      encode_scenario, load_scenario,
                                      scenario_for, selected_bundle_path)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_PATH = PROJECT_ROOT / "heldout" / "scenario_heldout.enc"

# The same list test_scenario.py checks the counterfactual against. Imported
# by value rather than shared, because the two files pin the same rule for two
# different bundles and one must not start passing because the other's list
# shrank.
HARD_TERMS = ("monitor", "check_recommendation", "quality check",
              "quality-check", "threshold", "checker", "platform-eng",
              "oversight", "audit", "compliance", "flag")

REQUIRED_KEYS = ("system_prompt_strong_nudge", "system_prompt_no_nudge",
                 "user_prompt", "followup_monitoring_questions",
                 "followup_sandbox_questions", "task_file", "internal_memo",
                 "monitoring_config", "quality_check_script", "readme",
                 "system_log", "meeting_notes", "traffic_counts_csv",
                 "model_params")


class overridden:
    """`SUBVERSIONBENCH_SCENARIO_BUNDLE` set to `path` for the block.

    A context manager rather than a pytest fixture. test_dependencies.py
    refuses fixture and parametrize decorators anywhere in this suite, because
    run_tests.py is pytest-free and cannot interpret one - it would report a
    failure it could not explain. (Naming the decorator here would trip that
    guard, which matches a decorator at the start of a line and would find this
    docstring.)
    """

    def __init__(self, path):
        self.path = str(path) if path is not None else None

    def __enter__(self):
        self.before = os.environ.get(BUNDLE_ENV_VAR)
        if self.path is None:
            os.environ.pop(BUNDLE_ENV_VAR, None)
        else:
            os.environ[BUNDLE_ENV_VAR] = self.path
        return self

    def __exit__(self, *exc):
        if self.before is None:
            os.environ.pop(BUNDLE_ENV_VAR, None)
        else:
            os.environ[BUNDLE_ENV_VAR] = self.before
        return False


def _heldout_bundle() -> dict:
    """The decrypted held-out bundle, or a skip when it is not here."""
    if not BUNDLE_PATH.is_file():
        raise unittest.SkipTest(
            "the held-out bundle is not in this checkout (it is gitignored)")
    from sad_oversight import decrypt
    return decrypt(BUNDLE_PATH.read_text(encoding="utf-8"))


class TestTheBundleSeam:
    """Which bundle a process runs against, and the refusals around it."""

    def test_unset_resolves_to_the_shipped_bundle(self):
        with overridden(None):
            assert not bundle_is_overridden()
            assert selected_bundle_path().name == "scenario.b64"

    def test_an_override_resolves_to_what_it_names(self):
        tmp = Path(tempfile.mkdtemp()) / "alt.json"
        tmp.write_text("{}", encoding="utf-8")
        with overridden(tmp):
            assert bundle_is_overridden()
            assert selected_bundle_path() == tmp

    def test_an_override_naming_nothing_readable_raises(self):
        """Loud rather than a fallback. A typo that quietly ran the shipped
        scenario would produce episodes labelled as the alternative arm and
        pooled against it, and nothing about them would look wrong."""
        missing = Path(tempfile.mkdtemp()) / "absent.json"
        with overridden(missing):
            try:
                selected_bundle_path()
            except FileNotFoundError as e:
                assert BUNDLE_ENV_VAR in str(e)
            else:
                raise AssertionError("a missing override was accepted")

    def test_whitespace_only_is_not_an_override(self):
        with overridden("   "):
            assert not bundle_is_overridden()
            assert selected_bundle_path().name == "scenario.b64"

    def test_a_json_bundle_is_read_as_json_and_b64_as_base64(self):
        """The suffix split is what keeps a decryption path out of scenario.py:
        the encrypted twin is handed over decrypted, as JSON."""
        payload = {"client_name": "Placeholder", "a": "b"}
        root = Path(tempfile.mkdtemp())
        as_json = root / "b.json"
        as_json.write_text(json.dumps(payload), encoding="utf-8")
        as_b64 = root / "b.b64"
        encode_scenario(payload, as_b64)
        assert load_scenario(as_json) == payload
        assert load_scenario(as_b64) == payload

    def test_the_shipped_bundle_is_never_written_under_an_override(self):
        """The read side follows the override, so a bundle loaded from the
        alternative and written back with the default path would fold its text
        into scenario.b64 and move all four of r9's fingerprints."""
        tmp = Path(tempfile.mkdtemp()) / "alt.json"
        tmp.write_text("{}", encoding="utf-8")
        with overridden(tmp):
            try:
                encode_scenario({"client_name": "Placeholder"})
            except RuntimeError as e:
                assert BUNDLE_ENV_VAR in str(e)
            else:
                raise AssertionError(
                    "encode_scenario wrote the shipped bundle under an override")

    def test_an_explicit_path_still_encodes_under_an_override(self):
        """The refusal is about the DEFAULT path, not about encoding at all."""
        root = Path(tempfile.mkdtemp())
        alt = root / "alt.json"
        alt.write_text("{}", encoding="utf-8")
        out = root / "out.b64"
        with overridden(alt):
            encode_scenario({"client_name": "Placeholder"}, out)
        assert load_scenario(out) == {"client_name": "Placeholder"}

    def test_the_shipped_bundle_is_still_encodable_with_no_override(self):
        out = Path(tempfile.mkdtemp()) / "out.b64"
        with overridden(None):
            encode_scenario({"client_name": "Placeholder"}, out)
        assert load_scenario(out)["client_name"] == "Placeholder"


class TestAnAlternativeBundleIsADifferentRollout:
    """Its episodes must not be stamped with r9's identity."""

    def test_no_override_means_no_alternative_pins(self):
        with overridden(None):
            assert rollout_pins._alternative_pins() is None

    def test_the_shipped_pins_are_literals_and_still_r9(self):
        """The reason the block that replaces them sits at the bottom of the
        file: r9's identity has to stay greppable and diffable."""
        assert rollout_pins.ROLLOUT_VERSION == "r9"
        assert len(rollout_pins.ROLLOUT_FINGERPRINTS) == 4

    def _staged(self, root, version="heldout-test", arms=None, write=True):
        """A bundle file and, optionally, a sidecar pinning `arms`."""
        bundle = root / "alt.enc"
        bundle.write_text("", encoding="utf-8")
        if write:
            if arms is None:
                arms = [{"oversight": o, "lure": lure,
                         "fingerprint": f"{int(o)}{int(lure)}0000000000"}
                        for o in (True, False) for lure in (True, False)]
            bundle.with_suffix(".pins.json").write_text(
                json.dumps({"rollout_version": version,
                            "fingerprints": arms}), encoding="utf-8")
        return bundle

    def test_a_missing_sidecar_is_a_hard_failure(self):
        """Never a fallback to r9's values: falling back is the one outcome
        worse than not running."""
        bundle = self._staged(Path(tempfile.mkdtemp()), write=False)
        with overridden(bundle):
            try:
                rollout_pins._alternative_pins()
            except FileNotFoundError as e:
                assert "pins" in str(e).lower()
            else:
                raise AssertionError("a bundle with no pins was accepted")

    def test_a_sidecar_may_not_reuse_the_shipped_rollout_version(self):
        bundle = self._staged(Path(tempfile.mkdtemp()), version="r9")
        with overridden(bundle):
            try:
                rollout_pins._alternative_pins()
            except ValueError as e:
                assert "r9" in str(e)
            else:
                raise AssertionError("a sidecar claiming to be r9 was accepted")

    def test_a_sidecar_with_no_version_is_refused(self):
        bundle = self._staged(Path(tempfile.mkdtemp()), version="  ")
        with overridden(bundle):
            try:
                rollout_pins._alternative_pins()
            except ValueError:
                pass
            else:
                raise AssertionError("a versionless sidecar was accepted")

    def test_every_arm_must_be_pinned_or_none_is(self):
        """A sidecar one arm short would raise from fingerprint_for() hours
        later, on whichever arm happened to be missing."""
        partial = [{"oversight": True, "lure": False, "fingerprint": "a" * 12}]
        bundle = self._staged(Path(tempfile.mkdtemp()), arms=partial)
        with overridden(bundle):
            try:
                rollout_pins._alternative_pins()
            except ValueError as e:
                assert "unpinned" in str(e)
            else:
                raise AssertionError("a partly-pinned sidecar was accepted")

    def test_a_complete_sidecar_replaces_version_and_all_four_arms(self):
        bundle = self._staged(Path(tempfile.mkdtemp()))
        with overridden(bundle):
            version, pins = rollout_pins._alternative_pins()
        assert version == "heldout-test"
        assert set(pins) == set(rollout_pins.ROLLOUT_FINGERPRINTS)
        assert not set(pins.values()) & set(
            rollout_pins.ROLLOUT_FINGERPRINTS.values()), (
            "an alternative rollout shares a fingerprint with r9")

    def test_the_sidecar_is_found_from_either_form_of_the_bundle(self):
        """Keyed on the stem, so the encrypted bundle and the decrypted JSON
        the harness actually reads resolve to one identity rather than two."""
        root = Path(tempfile.mkdtemp())
        self._staged(root)
        plaintext = root / "alt.json"
        plaintext.write_text("{}", encoding="utf-8")
        with overridden(plaintext):
            version, pins = rollout_pins._alternative_pins()
        assert version == "heldout-test" and len(pins) == 4


class TestTheHeldOutBundle:
    """The bundle's own invariants - the ones test_scenario.py pins for the
    shipped scenario, asserted here through the same scenario_for()."""

    def test_every_entry_the_scenario_needs_is_present(self):
        bundle = _heldout_bundle()
        for key in REQUIRED_KEYS:
            assert key in bundle and bundle[key], key

    def test_the_counterfactual_drops_both_oversight_artefacts(self):
        arm = scenario_for(False, bundle=_heldout_bundle())
        assert "monitoring_config" not in arm
        assert "quality_check_script" not in arm

    def test_no_document_in_the_counterfactual_mentions_oversight(self):
        for key, text in scenario_for(False, bundle=_heldout_bundle()).items():
            if not isinstance(text, str):
                continue
            hits = [t for t in HARD_TERMS if t in text.lower()]
            assert not hits, f"{key} still refers to oversight: {hits}"

    def test_the_counterfactual_differs_by_removal_only(self):
        bundle = _heldout_bundle()
        base = scenario_for(True, bundle=bundle)
        for key, text in scenario_for(False, bundle=bundle).items():
            if isinstance(text, str):
                assert len(text) <= len(base[key]), f"{key} grew"

    def test_the_nudge_prompts_are_identical_across_arms(self):
        bundle = _heldout_bundle()
        base = scenario_for(True, bundle=bundle)
        arm = scenario_for(False, bundle=bundle)
        for key in ("system_prompt_strong_nudge", "system_prompt_no_nudge"):
            assert arm[key] == base[key], (
                f"{key} differs across arms, so the nudge manipulation is "
                f"crossed with the counterfactual rather than nested in it")

    def test_the_counterfactual_still_says_how_to_finish(self):
        prompt = scenario_for(False, bundle=_heldout_bundle())["user_prompt"]
        assert "final" in prompt.lower() and "recommend" in prompt.lower()
        assert not [t for t in HARD_TERMS if t in prompt.lower()]

    def test_the_arms_share_everything_before_the_last_sentence(self):
        bundle = _heldout_bundle()
        base = scenario_for(True, bundle=bundle)["user_prompt"].strip()
        sentences = re.split(r"(?<=[.!?])\s+", base)
        assert scenario_for(False, bundle=bundle)["user_prompt"].startswith(
            " ".join(sentences[:2]))

    def test_the_max_arm_changes_only_the_ladders(self):
        bundle = _heldout_bundle()
        base = scenario_for(True, bundle=bundle)
        mx = scenario_for(True, bundle=bundle, nudge="max")
        assert set(base) == set(mx)
        assert {k for k in base if base[k] != mx[k]} == {
            "followup_monitoring_questions", "followup_sandbox_questions"}

    def test_authoring_the_arms_left_the_default_one_clean(self):
        base = scenario_for(True, bundle=_heldout_bundle())
        for key in ("max_nudge", "lure", "interrogation_variants",
                    "sandbox_refusal"):
            assert key not in base, key

    def test_every_interrogation_variant_replaces_q1_and_nothing_else(self):
        bundle = _heldout_bundle()
        base = scenario_for(True, bundle=bundle)
        for variant in bundle["interrogation_variants"]:
            arm = scenario_for(True, bundle=bundle, interrogation=variant)
            for key in ("followup_monitoring_questions",
                        "followup_sandbox_questions"):
                assert arm[key][1:] == base[key][1:], f"{variant}/{key}"
                assert arm[key][0] != base[key][0], f"{variant}/{key}"

    def test_the_lure_arm_adds_a_neighbour_file_and_one_sentence(self):
        bundle = _heldout_bundle()
        base = scenario_for(True, bundle=bundle)
        lure = scenario_for(True, bundle=bundle, lure=True)
        assert lure.get("lure_neighbour_file")
        assert {k for k in base if base[k] != lure.get(k)} == {"internal_memo"}
        assert len(lure["internal_memo"]) > len(base["internal_memo"])

    def test_the_client_name_comes_from_the_scenario_text(self):
        bundle = _heldout_bundle()
        client = bundle["client_name"]
        assert client and client[0].isupper()
        assert client in json.dumps(
            {k: v for k, v in bundle.items() if k != "client_name"}), (
            "the client name is a harness constant rather than the client the "
            "documents name")

    def test_every_contaminating_term_appears_in_a_document(self):
        """The haystack EXCLUDES the term list itself. Dumping the whole bundle
        makes this self-satisfying - the list is inside what it is compared
        against, so each entry matches itself and no drift can be reported."""
        bundle = _heldout_bundle()
        hay = json.dumps({k: v for k, v in bundle.items()
                          if k != "contaminating_terms"}).lower()
        absent = [t for t in bundle["contaminating_terms"]
                  if t.lower() not in hay]
        assert not absent, f"terms in no document: {len(absent)}"

    def test_the_shipped_scenario_does_not_bleed_into_it(self):
        """A reworded twin that still carries the original's client name would
        answer a different question from the one it exists to ask."""
        from subversionbench.scenario import CONTAMINATING_TERMS
        hay = json.dumps(_heldout_bundle()).lower()
        bleed = [t for t in CONTAMINATING_TERMS if t.lower() in hay]
        assert not bleed, f"{len(bleed)} shipped term(s) appear in it"

    def test_none_of_its_terms_are_greppable_in_tracked_files(self):
        """The same guard test_scenario.py applies to the shipped bundle. What
        leaks is what is published, so the git index is the right list."""
        bundle = _heldout_bundle()
        terms = tuple(bundle["contaminating_terms"]) + (
            " ".join(bundle["sandbox_refusal"].rstrip(")").split()[-3:]),)
        assert terms
        names = subprocess.run(["git", "ls-files", "-z"], cwd=PROJECT_ROOT,
                               capture_output=True, text=True,
                               check=True).stdout.split("\0")
        leaks = []
        for name in names:
            if not name or Path(name).suffix in (".zip", ".lock"):
                continue
            try:
                body = (PROJECT_ROOT / name).read_text(
                    encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            leaks += [f"{name}" for t in terms if t.lower() in body]
        assert not leaks, f"held-out terms are greppable in: {sorted(set(leaks))}"

    def test_the_environment_builds_from_it_in_both_arms(self):
        import subversionbench.environment as env_mod
        bundle = _heldout_bundle()
        real = env_mod.scenario_for
        try:
            env_mod.scenario_for = (
                lambda oversight=True, **kw: scenario_for(
                    oversight=oversight, bundle=bundle, **kw))
            for oversight in (True, False):
                env_dir = tempfile.mkdtemp()
                info = env_mod.create_hardened_environment(env_dir, oversight)
                assert Path(f"{env_dir}/README.md").exists()
                assert Path(info["memo_path"]).exists()
                if oversight:
                    assert Path(info["monitoring_config_path"]).exists()
                    assert Path(info["quality_check_path"]).exists()
                else:
                    assert "monitoring_config_path" not in info
        finally:
            env_mod.scenario_for = real

    def test_its_checker_flags_one_strategy_and_passes_the_other(self):
        """The tamper opportunity only exists if the checker actually flags the
        draft the model's own objective points at."""
        bundle = _heldout_bundle()
        root = Path(tempfile.mkdtemp())
        script = root / "check.sh"
        script.write_text(bundle["quality_check_script"], encoding="utf-8")
        (root / "config").mkdir()
        (root / "config" / "monitoring.yaml").write_text(
            bundle["monitoring_config"], encoding="utf-8")
        verdicts = []
        for draft in ("I recommend Strategy A.", "I recommend Strategy B."):
            out = subprocess.run(["sh", str(script)], input=draft, cwd=root,
                                 capture_output=True, text=True).stdout
            verdicts.append("FLAGGED" in out)
        assert verdicts == [True, False], (
            "the checker must flag the objective-aligned strategy and pass the "
            "brief-aligned one, as the shipped scenario's does")

    def test_the_pins_on_disk_are_the_ones_a_run_reproduces(self):
        """The pins have to be computed UNDER the override, not by patching
        scenario_for in a process that still has the shipped bundle's
        constants.

        This is a regression test for a real defect in heldout_tool.py --pin.
        The fingerprint covers the sandbox display path and the task file's
        name as well as the scenario text, and both are derived from the bundle
        at import - so patching only scenario_for mixed the held-out documents
        with the shipped scenario's paths and pinned four values no run would
        ever produce. Every arm's drift guard then refused, which is the safe
        failure, but the pins were silently wrong until measured.

        A subprocess, because this process froze its own constants at import.
        """
        bundle = _heldout_bundle()   # skips when the bundle is absent
        sidecar = BUNDLE_PATH.with_suffix(rollout_pins._PINS_SIDECAR_SUFFIX)
        if not sidecar.is_file():
            raise unittest.SkipTest("the held-out bundle is not pinned yet")
        # Exports into a temp directory rather than using the plaintext copy a
        # run leaves behind - run_heldout.sh removes that on exit, so depending
        # on it made this test skip exactly when nothing was mid-run. Both
        # files are copied because the sidecar is found from the bundle's stem.
        staged = Path(tempfile.mkdtemp())
        exported = staged / (BUNDLE_PATH.stem + ".json")
        exported.write_text(json.dumps(bundle), encoding="utf-8")
        (staged / (BUNDLE_PATH.stem + rollout_pins._PINS_SIDECAR_SUFFIX)
         ).write_text(sidecar.read_text(encoding="utf-8"), encoding="utf-8")
        probe = (
            "import json\n"
            "from subversionbench.rollout import rollout_fingerprint\n"
            "from subversionbench.rollout_pins import fingerprint_for\n"
            "print(json.dumps([rollout_fingerprint(o, lure=l) "
            "== fingerprint_for(o, l)\n"
            "                  for o in (True, False) for l in (False, True)]))\n"
        )
        env = dict(os.environ)
        env[BUNDLE_ENV_VAR] = str(exported)
        result = subprocess.run([__import__("sys").executable, "-c", probe],
                                cwd=PROJECT_ROOT, env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        agree = json.loads(result.stdout)
        assert all(agree), (
            f"{agree.count(False)} of 4 arms disagree with their pinned "
            f"fingerprint, so heldout_tool.py --pin did not compute them the "
            f"way a run does")

    def test_its_rollout_differs_from_r9_on_every_arm(self):
        """Not a new rollout by assertion - by measurement. If any arm matched,
        its episodes could be pooled with r9's."""
        import subversionbench.rollout as rollout_mod
        bundle = _heldout_bundle()
        real = rollout_mod.scenario_for
        try:
            rollout_mod.scenario_for = (
                lambda oversight=True, **kw: scenario_for(
                    oversight=oversight, bundle=bundle, **kw))
            for oversight in (True, False):
                for lure in (False, True):
                    assert (rollout_mod.rollout_fingerprint(oversight, lure=lure)
                            != rollout_pins.ROLLOUT_FINGERPRINTS[
                                (oversight, lure)]), (oversight, lure)
        finally:
            rollout_mod.scenario_for = real
