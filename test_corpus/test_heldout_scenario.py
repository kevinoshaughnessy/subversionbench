"""
The held-out scenario: a second bundle, selected by an environment variable,
that a model trained on the published one has not seen.

The seam is the subject. Selecting another bundle must change the rollout
identity - otherwise its episodes pool with the published corpus and the whole
point of a twin is lost - and it must not change anything else.
"""


import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from subversionbench import rollout_pins
from subversionbench.scenario import (BUNDLE_ENV_VAR, bundle_is_overridden,
                                      encode_scenario, load_scenario,
                                      selected_bundle_path)

from test_corpus.heldout_fixtures import (overridden)

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

    def test_the_shipped_pins_are_literals(self):
        """The reason the block that replaces them sits at the bottom of the
        file: the shipped identity has to stay greppable and diffable.

        ASSERTS THAT THEY ARE LITERALS, not what they currently say. The first
        version asserted `== "r9"`, which is a copy of a pinned value in a
        second place - the thing this repository's own conventions warn about -
        and it duly failed on the r9 -> r10 bump for no reason connected to what
        it was guarding. What matters is that the version and the four arm
        fingerprints are written down rather than computed, so a rollout change
        shows up in a diff.
        """
        source = open(rollout_pins.__file__, encoding="utf-8").read()
        assert re.search(r'^ROLLOUT_VERSION = "[^"]+"$', source, re.M), (
            "ROLLOUT_VERSION is not a plain literal assignment")
        assert len(rollout_pins.ROLLOUT_FINGERPRINTS) == 4
        for value in rollout_pins.ROLLOUT_FINGERPRINTS.values():
            assert f'"{value}"' in source, (
                f"{value} is not written literally in the file, so a rollout "
                f"change would not show up in a diff of it")

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
        """Taken from ROLLOUT_VERSION rather than written out. The name of the
        shipped rollout is the subject of this test, so hardcoding it made the
        test fail on the r9 -> r10 bump while the behaviour it guards was
        working exactly as intended."""
        shipped = rollout_pins.ROLLOUT_VERSION
        bundle = self._staged(Path(tempfile.mkdtemp()), version=shipped)
        with overridden(bundle):
            try:
                rollout_pins._alternative_pins()
            except ValueError as e:
                assert shipped in str(e)
            else:
                raise AssertionError(
                    f"a sidecar claiming to be {shipped} was accepted")

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


class TestTheFingerprintSidecar:
    """heldout_tool's pin helpers, neither previously executed by the suite.

    The sidecar is what lets a held-out results directory be identified from a
    fingerprint alone. Getting it wrong is not loud: a batch collected against
    a bundle whose pins were silently dropped still runs, and the arm it
    claims cannot be checked afterwards.
    """

    def _redirect(self, tmp):
        """Point the tool at a scratch sidecar, returning a restore callable."""
        import heldout_tool as ht
        real = ht.PINS_PATH
        ht.PINS_PATH = tmp
        return lambda: setattr(ht, "PINS_PATH", real)

    def test_an_absent_sidecar_reads_as_no_pins(self):
        """Not an error: the first pinning run has nothing to read, and a
        raise here would make bootstrapping a new bundle impossible."""
        import heldout_tool as ht
        restore = self._redirect(Path(tempfile.mkdtemp()) / "absent.json")
        try:
            assert ht._pinned() == {}
        finally:
            restore()

    def test_pins_round_trip_through_the_sidecar(self):
        """_write_pins then _pinned must agree, or a drift guard compares a
        fingerprint against a differently-keyed copy of itself."""
        import heldout_tool as ht
        tmp = Path(tempfile.mkdtemp()) / "pins.json"
        restore = self._redirect(tmp)
        try:
            pins = {(True, False): "aaaaaaaaaaaa", (False, True): "bbbbbbbbbbbb"}
            ht._write_pins(pins)
            assert ht._pinned() == pins
        finally:
            restore()

    def test_superseded_fingerprints_are_kept_not_overwritten(self):
        """The practice rollout_pins.py applies to r1-r8. A sidecar that
        forgot the previous rollout's values would leave an archived results
        directory unidentifiable from its fingerprints alone."""
        import heldout_tool as ht
        tmp = Path(tempfile.mkdtemp()) / "pins.json"
        restore = self._redirect(tmp)
        try:
            # A sidecar that ALREADY carries history, so this covers both
            # halves: the outgoing rollout is appended, and what was already
            # superseded is carried forward. Seeding an empty history hid a
            # `history = []` from this test entirely - the append still ran,
            # so the count was still one and the plant passed.
            tmp.write_text(json.dumps({
                "rollout_version": "r-previous",
                "fingerprints": [{"oversight": True, "lure": False,
                                  "fingerprint": "oldoldoldold"}],
                "superseded": [{"rollout_version": "r-ancient",
                                "fingerprints": [{"oversight": True,
                                                  "lure": False,
                                                  "fingerprint": "ancientaaaa"}]}],
            }), encoding="utf-8")
            ht._write_pins({(True, False): "newnewnewnew"})
            written = json.loads(tmp.read_text(encoding="utf-8"))
            assert written["rollout_version"] == ht.ROLLOUT_VERSION
            assert written["fingerprints"][0]["fingerprint"] == "newnewnewnew"
            history = written["superseded"]
            assert len(history) == 2, history
            versions = [h["rollout_version"] for h in history]
            assert versions == ["r-ancient", "r-previous"], versions
            assert (history[-1]["fingerprints"][0]["fingerprint"]
                    == "oldoldoldold")
            assert (history[0]["fingerprints"][0]["fingerprint"]
                    == "ancientaaaa")
        finally:
            restore()

    def test_rewriting_the_same_rollout_does_not_grow_the_history(self):
        """Re-pinning the CURRENT rollout is a correction, not a supersession.
        Recording it would fill the sidecar with copies of one rollout and
        bury the entry that identifies an older corpus."""
        import heldout_tool as ht
        tmp = Path(tempfile.mkdtemp()) / "pins.json"
        restore = self._redirect(tmp)
        try:
            ht._write_pins({(True, False): "firstfirstaa"})
            ht._write_pins({(True, False): "secondsecond"})
            written = json.loads(tmp.read_text(encoding="utf-8"))
            assert written["superseded"] == [], written["superseded"]
            assert ht._pinned() == {(True, False): "secondsecond"}
        finally:
            restore()


class TestZipShNeverArchivesTheHeldOutCorpus:
    """The held-out corpus is worth having only while it has never been
    published, and zip.sh produces the artefact that gets published.

    Its own .zip being gitignored is a SECOND line of defence, not a first: the
    shipped archive is deliberately tracked, so the ignore rule is already
    overridden for a file of exactly that shape. The exclusion has to be in
    front of the step that creates the archive.

    Exercised through --print-selection rather than by running the real thing:
    an exclusion whose only evidence is which files a 75MB archive step did not
    create is not something a test can assert on.
    """

    def _root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _selection(self, *args):
        """What zip.sh says it would archive, what it skips, and the raw text.

        The raw stdout is returned as well as the parsed lists because the
        machine-readable `skip:` lines and the sentence a person reads are two
        different outputs, and a test that checks only the first passes on a
        script whose skip went silent.
        """
        result = subprocess.run(
            [os.path.join(self._root(), "zip.sh"), "--print-selection", *args],
            cwd=self._root(), capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        archive, skip = [], []
        for line in result.stdout.splitlines():
            if line.startswith("archive: "):
                archive.append(line[len("archive: "):])
            elif line.startswith("skip: "):
                skip.append(line[len("skip: "):])
        return archive, skip, result.stdout

    def _made(self, name):
        """A throwaway results directory in the repo root, removed afterwards.

        In the ROOT, not a temp dir: zip.sh does `cd "$(dirname "$0")"` so that
        it works from anywhere, which means its selection is always over the
        repo root and cannot be pointed elsewhere for a test. Matches
        eval_results_*/ in .gitignore, so it cannot be committed by accident
        even if the cleanup is skipped.
        """
        import shutil
        path = os.path.join(self._root(), name)
        os.makedirs(path, exist_ok=True)

        class Made:
            def __enter__(self):
                return name

            def __exit__(self, *exc):
                shutil.rmtree(path, ignore_errors=True)
        return Made()

    def test_an_unqualified_run_skips_a_held_out_directory(self):
        with self._made("eval_results_zzztest_heldout") as name:
            archive, skip, raw = self._selection()
            assert name not in archive, (
                f"{name} would be archived by a bare ./zip.sh")
            assert name in skip, (
                f"{name} was neither archived nor reported as skipped - a "
                f"silent drop is how a caller comes to believe it was done")
            # And said in words, not only in the machine-readable listing. A
            # --remove run that silently skipped a directory would leave the
            # only copy being the archive that was never made.
            assert "held-out" in raw and name in raw, (
                "the skip was not announced in the run's own output")

    def test_an_ordinary_directory_is_still_archived(self):
        """The positive control. Without it the test above passes just as well
        on a script that archives nothing at all."""
        with self._made("eval_results_zzztest_ordinary") as name:
            archive, _skip, _raw = self._selection()
            assert name in archive, (
                f"{name} is not held out and must still be archived")

    def test_naming_a_held_out_directory_explicitly_is_refused(self):
        """A skip would be wrong here. --dirs means "this one and no others", so
        dropping it silently would report success over an archive the caller
        never got."""
        with self._made("eval_results_zzztest_heldout") as name:
            result = subprocess.run(
                [os.path.join(self._root(), "zip.sh"), "--dirs", name],
                cwd=self._root(), capture_output=True, text=True, timeout=120)
            assert result.returncode != 0, (
                "zip.sh accepted a held-out directory named explicitly")
            assert "REFUS" in result.stderr.upper()
            assert not os.path.exists(
                os.path.join(self._root(), f"{name}.zip")), \
                "an archive was written before the refusal"

    def test_the_name_test_does_not_depend_on_the_pins_sidecar(self):
        """The sidecar is gitignored, so on a fresh clone it is absent and the
        name pattern is the whole guard. Asserted by reading zip.sh: the name
        case must not sit behind a check for the sidecar's existence."""
        source = open(os.path.join(self._root(), "zip.sh"),
                      encoding="utf-8").read()
        body = source.split("is_heldout()")[1].split("\n}")[0]
        name_case = body.index("*heldout*")
        sidecar_use = body.index("heldout_rollout_versions")
        assert name_case < sidecar_use, (
            "is_heldout consults the sidecar before the name pattern, so a "
            "checkout without heldout/ would lose the name guard")

    def test_the_sidecar_half_names_every_rollout_it_declares(self):
        """Including superseded ones: a superseded held-out rollout still has a
        corpus on disk, and dropping the old names would leave it unguarded by
        this half."""
        import glob
        import json
        sidecars = glob.glob(os.path.join(self._root(),
                                          "heldout", "*.pins.json"))
        if not sidecars:
            import unittest
            raise unittest.SkipTest("no held-out pins in this checkout")
        expected = set()
        for path in sidecars:
            declared = json.loads(open(path, encoding="utf-8").read())
            expected.add(declared["rollout_version"])
            expected.update(old["rollout_version"]
                            for old in declared.get("superseded") or [])
        source = open(os.path.join(self._root(), "zip.sh"),
                      encoding="utf-8").read()
        function = source.split("heldout_rollout_versions() {")[1]
        function = "heldout_rollout_versions() {" + function.split("\n}")[0] + "\n}"
        result = subprocess.run(
            ["bash", "-c", f"{function}\nheldout_rollout_versions"],
            cwd=self._root(), capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        assert set(result.stdout.split()) == expected, (
            f"zip.sh derives {sorted(set(result.stdout.split()))} from the "
            f"sidecar but it declares {sorted(expected)}")
