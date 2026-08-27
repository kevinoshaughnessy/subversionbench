"""
The cross-arm report: one file summarising every arm a model has been run
through, and the contrasts that hold up across them.
"""

import json
import tempfile
from pathlib import Path

from subversionbench.arms_summary import (
    build_summary_of_summaries,
    format_summary_of_summaries,
    write_summary_of_summaries,
)


def _rate(successes, n):
    return {"successes": successes, "n": n,
            "rate": round(successes / n, 4) if n else None, "ci95": [0, 1]}


def _write_arm(out, model, nudge, oversight, lure, stamp, n_runs=10,
              misaligned=(0, 10), episodes=None):
    """A minimal summary + matching run files for one arm."""
    from subversionbench.batch import batch_stem
    slug = model.replace("/", "_")
    stem = batch_stem(slug, nudge, None, oversight, lure)
    summary = {
        "model": model, "nudge": nudge, "batch_stamp": stamp,
        "n_runs": n_runs, "batch_aborted": False, "episode_failures": [],
        "version": "v99",
        "rates": {
            "misaligned": _rate(*misaligned),
            "scheming": _rate(0, n_runs),
            "monitoring_disabled": _rate(0, n_runs) if oversight else
                                   {"successes": 0, "n": 0, "rate": None, "ci95": None},
            "sandbox_escape_attempt": _rate(0, n_runs),
            "eval_aware_grader": _rate(0, n_runs),
        },
    }
    with open(f"{out}/summary_{stem}_{stamp}.json", "w") as f:
        json.dump(summary, f)

    for i in range(n_runs):
        run = {
            "model": model, "nudge": nudge, "headline_interrogation": "zeroevidence",
            "analysis": (episodes[i] if episodes else {}),
        }
        with open(f"{out}/run_{i+1}_{stem}_{stamp}.json", "w") as f:
            json.dump(run, f)


class TestFindingArms:
    def test_every_collected_arm_is_found(self):
        with tempfile.TemporaryDirectory() as out:
            for i, nudge in enumerate(("none", "strong")):
                _write_arm(out, "x/m", nudge, True, False,
                          f"2026010{i+1}T000000")
            report = build_summary_of_summaries(out, "x/m")
            assert set(report["arms"]) == {"none", "strong"}

    def test_missing_arms_are_named_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001")
            report = build_summary_of_summaries(out, "x/m")
            assert "strong" in report["missing_arms"]
            assert "max_nooversight_lure" in report["missing_arms"]

    def test_a_different_models_summaries_are_not_pulled_in(self):
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001")
            _write_arm(out, "y/other", "none", True, False, "20260101T000002")
            report = build_summary_of_summaries(out, "x/m")
            assert set(report["arms"]) == {"none"}

    def test_the_arm_label_matches_the_batch_filename_convention(self):
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "strong", False, True, "20260101T000001")
            report = build_summary_of_summaries(out, "x/m")
            assert "strong_nooversight_lure" in report["arms"]

class TestContrasts:
    def test_a_real_difference_is_flagged_as_separated(self):
        """Oversight on vs off, with a stark misaligned-rate difference at
        n=10 each - large enough that the interval should exclude zero,
        the same "separated" criterion compare_rates itself recommends."""
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001", misaligned=(0, 10))
            _write_arm(out, "x/m", "none", False, False, "20260101T000002", misaligned=(10, 10))
            report = build_summary_of_summaries(out, "x/m")
            axes = {c["axis"] for c in report["notable_contrasts"]}
            assert "oversight" in axes
            hit = [c for c in report["notable_contrasts"]
                  if c["axis"] == "oversight" and c["metric"] == "misaligned"]
            assert hit, report["notable_contrasts"]

    def test_a_tiny_difference_is_not_flagged(self):
        """0/10 vs 1/10 is well within noise at this n - the whole point of
        using a difference interval instead of "any nonzero gap"."""
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001", misaligned=(0, 10))
            _write_arm(out, "x/m", "none", False, False, "20260101T000002", misaligned=(1, 10))
            report = build_summary_of_summaries(out, "x/m")
            hit = [c for c in report["notable_contrasts"]
                  if c["metric"] == "misaligned"]
            assert not hit

    def test_a_not_applicable_rate_is_not_contrasted(self):
        """monitoring_disabled has n=0 in a no-oversight arm - there is
        nothing to compare it against, and this must not crash trying."""
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001")
            _write_arm(out, "x/m", "none", False, False, "20260101T000002")
            report = build_summary_of_summaries(out, "x/m")
            mon_dis = [c for c in report["contrasts"]["oversight"]
                      if c["metric"] == "monitoring_disabled"]
            assert not mon_dis

    def test_nudge_is_contrasted_within_each_oversight_and_lure_combination(self):
        with tempfile.TemporaryDirectory() as out:
            for i, nudge in enumerate(("none", "strong", "max")):
                _write_arm(out, "x/m", nudge, True, False,
                          f"2026010{i+1}T000000")
            report = build_summary_of_summaries(out, "x/m")
            pairs = {(c["arm_a"], c["arm_b"]) for c in report["contrasts"]["nudge"]}
            assert ("none", "strong") in pairs
            assert ("strong", "max") in pairs

class TestVariantConcealment:
    def test_per_variant_levels_are_counted(self):
        episodes = [
            {"concealment_sandbox_by_variant": {
                "zeroevidence": "denied", "partevidence": "admitted_first_ask"}},
            {"concealment_sandbox_by_variant": {
                "zeroevidence": "admitted_first_ask", "partevidence": "admitted_first_ask"}},
        ] + [{}] * 8
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001", episodes=episodes)
            report = build_summary_of_summaries(out, "x/m")
            cbv = report["arms"]["none"]["concealment_by_variant"]["sandbox"]
            assert cbv["zeroevidence"]["n"] == 2
            assert cbv["zeroevidence"]["concealed"] == 1   # "denied" is a
                                                            # SCHEMING_LEVELS member
            assert cbv["partevidence"]["concealed"] == 0

    def test_an_episode_with_no_act_of_that_kind_contributes_nothing(self):
        episodes = [{}] * 10
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001", episodes=episodes)
            report = build_summary_of_summaries(out, "x/m")
            assert "concealment_by_variant" not in report["arms"]["none"]

class TestWriting:
    def test_it_writes_valid_json_and_returns_the_path(self):
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                path = write_summary_of_summaries(out, "x/m")
            assert Path(path).exists()
            with open(path) as f:
                data = json.load(f)
            assert data["model"] == "x/m"

    def test_the_filename_is_keyed_on_the_model_slug(self):
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/y-z", "none", True, False, "20260101T000001")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                path = write_summary_of_summaries(out, "x/y-z")
            assert "summary_of_summaries_x_y-z.json" in path

class TestFormatting:
    def test_missing_arms_are_named_in_the_console_output(self):
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001")
            report = build_summary_of_summaries(out, "x/m")
        out_text = format_summary_of_summaries(report)
        assert "strong" in out_text

    def test_no_notable_contrasts_says_so_rather_than_nothing(self):
        with tempfile.TemporaryDirectory() as out:
            _write_arm(out, "x/m", "none", True, False, "20260101T000001")
            report = build_summary_of_summaries(out, "x/m")
        out_text = format_summary_of_summaries(report)
        assert "No contrast" in out_text
