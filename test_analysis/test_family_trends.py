"""
`python3 -m trends`: which metrics run, where the JSON goes, and what a
directory it cannot answer produces.
"""


import json
import os
import tempfile

import trends as ft
from test_analysis.report_fixtures import _write_summary


class TestWhereTheJsonGoes:
    """Two metrics of one corpus are two different reports. A directory of
    timestamped files gives no way to tell which is which without opening
    them - and the charts already name their metric, so the JSON beside them
    reading only `family_trends_<timestamp>` was the odd one out."""

    def _corpus(self, out):
        for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5),
                                  ("p/rise-1", 1), ("p/rise-2", 6)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def _run(self, out, *extra):
        import contextlib
        import io
        import sys
        argv = sys.argv
        sys.argv = ["family_trends.py", "--output-dir", out, "--no-charts",
                    *extra]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert ft.main() == 0
        finally:
            sys.argv = argv
        return sorted(f for f in os.listdir(out)
                      if f.startswith("family_trends_"))

    def test_the_metric_is_in_the_default_filename(self):
        with tempfile.TemporaryDirectory() as out:
            written = self._run(self._corpus(out), "--metric", "aware")
            assert len(written) == 1
            assert written[0].startswith("family_trends_aware_")
            assert written[0].endswith(".json")

    def test_two_metrics_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            self._run(out, "--metric", "misaligned")
            written = self._run(out, "--metric", "scheming")
            assert len(written) == 2
            assert any("_misaligned_" in f for f in written)
            assert any("_scheming_" in f for f in written)

    def test_an_explicit_json_out_still_wins(self):
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            target = os.path.join(out, "named.json")
            self._run(out, "--json-out", target)
            assert os.path.exists(target)
            with open(target) as f:
                assert json.load(f)["metric"] == "misaligned"

    def test_the_default_matches_what_the_help_promises(self):
        """The help lives in main; the filename is built one call down, where
        `--metric all` loops over it."""
        import inspect
        assert "family_trends_<metric>_<timestamp>.json" in inspect.getsource(
            ft.main)
        assert 'f"family_trends_{metric}_' in inspect.getsource(
            ft._report_one_metric)


class TestRunningEveryMetric:
    """`--metric all` expands into ordinary single-metric runs rather than
    growing a second implementation beside them."""

    def _corpus(self, out):
        for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5),
                                  ("p/rise-1", 1), ("p/rise-2", 6)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def _run(self, out, *extra):
        import contextlib
        import io
        import sys
        argv = sys.argv
        sys.argv = ["family_trends.py", "--output-dir", out, "--no-charts",
                    *extra]
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                code = ft.main()
        finally:
            sys.argv = argv
        return code, buf.getvalue(), sorted(
            f for f in os.listdir(out) if f.startswith("family_trends_"))

    def test_all_is_not_itself_a_metric(self):
        """It is expanded by the loop, never looked up as one."""
        assert ft.METRIC_ALL not in ft.METRICS

    def test_it_writes_one_report_per_metric(self):
        """One per metric this corpus can answer. The fixture writes summaries
        and no run files, so the episode-derived metric is skipped - and the
        skip must not cost the others their reports or the run its exit code."""
        with tempfile.TemporaryDirectory() as out:
            code, _printed, written = self._run(self._corpus(out),
                                                "--metric", "all")
            assert code == 0
            from_summaries = [m for m, spec in ft.METRICS.items()
                              if not spec.get("from_episodes")]
            assert len(written) == len(from_summaries)
            for metric in from_summaries:
                assert any(f"_{metric}_" in name for name in written), metric

    def test_an_episode_derived_metric_skips_rather_than_fails(self):
        """`--metric all` over a summaries-only directory must still succeed.
        Returning a failure would make one unanswerable metric look like a
        broken run and hide the three that computed."""
        with tempfile.TemporaryDirectory() as out:
            code, printed, _written = self._run(self._corpus(out),
                                                "--metric", ft.TEXT_REACHABLE)
            assert code == 0
            assert "derived per episode" in printed

    def test_the_reports_share_one_timestamp(self):
        """A single run should sort together, not be split by however long it
        took to produce."""
        with tempfile.TemporaryDirectory() as out:
            _code, _printed, written = self._run(self._corpus(out),
                                                 "--metric", "all")
            stamps = {name.rsplit("_", 1)[1] for name in written}
            assert len(stamps) == 1

    def test_each_metric_is_announced(self):
        with tempfile.TemporaryDirectory() as out:
            _code, printed, _written = self._run(self._corpus(out),
                                                 "--metric", "all")
            for metric in ft.METRICS:
                assert f"# metric: {metric}" in printed, metric

    def test_each_report_carries_its_own_metric(self):
        with tempfile.TemporaryDirectory() as out:
            _code, _printed, written = self._run(self._corpus(out),
                                                 "--metric", "all")
            for name in written:
                with open(os.path.join(out, name)) as f:
                    report = json.load(f)
                assert f"_{report['metric']}_" in name

    def test_a_single_metric_still_announces_nothing(self):
        """The banner is noise when there is only one report."""
        with tempfile.TemporaryDirectory() as out:
            _code, printed, _written = self._run(self._corpus(out),
                                                 "--metric", "aware")
            assert "# metric:" not in printed

    def test_json_out_with_all_is_refused(self):
        """One path cannot hold three reports, and silently overwriting twice
        would leave only the last."""
        import contextlib
        import io
        import sys
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            argv = sys.argv
            sys.argv = ["family_trends.py", "--output-dir", out, "--no-charts",
                        "--metric", "all", "--json-out",
                        os.path.join(out, "one.json")]
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    try:
                        ft.main()
                        raised = False
                    except SystemExit:
                        raised = True
            finally:
                sys.argv = argv
            assert raised, "--json-out with --metric all must not proceed"
            assert "--json-out" in err.getvalue()

    def test_the_charts_of_each_metric_do_not_collide(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        import contextlib
        import io
        import sys
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            charts = os.path.join(out, "charts")
            argv = sys.argv
            sys.argv = ["family_trends.py", "--output-dir", out,
                        "--metric", "all", "--chart-dir", charts]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    assert ft.main() == 0
            finally:
                sys.argv = argv
            # Two families plus one combined, per metric that this corpus
            # can answer. text_reachable is derived per episode and the fixture
            # writes summaries only, so it contributes no charts and must not
            # stop the others being drawn.
            from_summaries = [m for m, spec in ft.METRICS.items()
                              if not spec.get("from_episodes")]
            assert len(os.listdir(charts)) == 3 * len(from_summaries)


class TestACorpusWithNoFamilyIsReportedTwoDifferentWays:
    """Both are "no families found", and they mean opposite things about the
    run. A summary-only corpus genuinely cannot answer an episode-derived
    metric, so `--metric all` must keep going and exit zero; a corpus whose
    models simply share no family is a real empty result and exits one. One
    message for both would tell an operator to go looking for run files that
    were never needed."""

    def _run(self, out, *extra):
        import contextlib
        import io
        import sys
        argv = sys.argv
        sys.argv = ["family_trends.py", "--output-dir", out, "--no-charts",
                    *extra]
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                code = ft.main()
        finally:
            sys.argv = argv
        return code, buf.getvalue()

    def _a_summary_only_metric(self):
        """A metric this corpus's summaries can answer, taken from METRICS
        rather than named, so one added later is covered by these tests."""
        return next(m for m, spec in ft.METRICS.items()
                    if not spec.get("from_episodes"))

    def _an_episode_derived_metric(self):
        return next(m for m, spec in ft.METRICS.items()
                    if spec.get("from_episodes"))

    def test_models_that_share_no_family_are_an_empty_result(self):
        with tempfile.TemporaryDirectory() as out:
            for model in ("alpha/one-1", "beta/two-1", "gamma/three-1"):
                _write_summary(out, model, "strong", n_runs=10,
                               n_misaligned=2, n_scheming=1)
            code, text = self._run(out, "--metric", self._a_summary_only_metric())
        assert code == 1, text
        assert "No family with two or more members" in text
        assert "Skipping" not in text

    def test_a_summary_only_corpus_skips_an_episode_metric_without_failing(self):
        with tempfile.TemporaryDirectory() as out:
            for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5)):
                _write_summary(out, model, "strong", n_runs=10,
                               n_misaligned=misaligned, n_scheming=1)
            code, text = self._run(out, "--metric",
                                   self._an_episode_derived_metric())
        assert code == 0, text
        assert "holds no run files" in text
        assert "No family with two or more members" not in text

    def test_a_real_family_reports_rather_than_taking_either_branch(self):
        """The control for both."""
        with tempfile.TemporaryDirectory() as out:
            for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5)):
                _write_summary(out, model, "strong", n_runs=10,
                               n_misaligned=misaligned, n_scheming=1)
            code, text = self._run(out, "--metric",
                                   self._a_summary_only_metric())
        assert code == 0, text
        assert "No family with two or more members" not in text
        assert "Skipping" not in text


class TestTheCliRefusesADirectoryThatIsNotThere:
    def test_a_missing_output_dir_exits_one_and_names_it(self):
        import contextlib
        import io
        import sys
        argv = sys.argv
        with tempfile.TemporaryDirectory() as parent:
            missing = os.path.join(parent, "not-a-directory")
            sys.argv = ["family_trends.py", "--output-dir", missing,
                        "--no-charts"]
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    code = ft.main()
            finally:
                sys.argv = argv
        assert code == 1, buf.getvalue()
        assert "No such directory" in buf.getvalue()
        assert "not-a-directory" in buf.getvalue()
