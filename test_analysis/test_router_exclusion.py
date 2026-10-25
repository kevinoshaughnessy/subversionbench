"""
Routers are kept out of the report's corpus (report/exclusions.py).

A router's episodes are an unknown mixture of models, so no figure pooled
across models may include them. Excluded before anything reads the corpus,
from summaries, episodes and failed episodes alike, and named in the document
and on the console - never silently.
"""

import contextlib
import io
import tempfile

import report as rr
from report.console import _print_router_exclusion
from report.exclusions import (ROUTER_MODELS, UNRUNNABLE_MODELS,
                               exclude_routers)
from test_analysis.report_fixtures import (_write_episode,
                                           _write_failed_episode,
                                           _write_summary)

ROUTER = ROUTER_MODELS[0]


def _corpus():
    out = tempfile.mkdtemp()
    for i in range(3):
        _write_episode(out, i, "m/a", "strong", tampered=True,
                       monitoring=True)
    _write_episode(out, 9, ROUTER, "strong", tampered=True, monitoring=True)
    _write_summary(out, "m/a", "strong", n_runs=3, n_misaligned=3)
    _write_summary(out, ROUTER, "strong", n_runs=1, n_misaligned=1)
    _write_failed_episode(out, 7, ROUTER, "strong")
    return out


class TestTheRouterIsNotInTheCorpus:
    def test_it_is_in_no_figure(self):
        report = rr.build_report(_corpus())
        assert report["n_episode_files"] == 3
        assert report["n_summary_files"] == 1
        assert report["n_models"] == 1
        pooled = report["characteristics"]["act_forms"]["pooled"]["oversight"]
        assert pooled["n_observable"] == 3

    def test_it_is_named_and_counted(self):
        stamp = rr.build_report(_corpus())["routers_excluded"]
        assert stamp["models"] == list(ROUTER_MODELS)
        assert (stamp["n_episodes_dropped"], stamp["n_summaries_dropped"],
                stamp["n_failed_dropped"]) == (1, 1, 1)

    def test_the_failed_episodes_lose_it_too(self):
        """A router's API losses counted against the models left would be a
        split-corpus claim, as exclude_arm says of the arm exclusion."""
        quality = rr.build_report(_corpus())["data_quality"]
        assert ROUTER not in str(quality)


class TestTheFilterItself:
    def test_every_other_model_is_kept(self):
        rows = [{"model": "m/a"}, {"model": ROUTER}, {"model": "m/b"}]
        kept, _, _, stamp = exclude_routers(rows, [], [])
        assert [r["model"] for r in kept] == ["m/a", "m/b"]
        assert stamp["n_summaries_dropped"] == 1


class TestItIsSaidOnTheConsole:
    def test_printed_when_the_corpus_held_one(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_router_exclusion(rr.build_report(_corpus())["routers_excluded"])
        assert "ROUTERS EXCLUDED" in buf.getvalue() and ROUTER in buf.getvalue()

    def test_silent_when_it_held_none(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_router_exclusion(exclude_routers([], [], [])[3])
        assert buf.getvalue() == ""


UNRUNNABLE = UNRUNNABLE_MODELS[0]


def _corpus_with_unrunnable():
    out = _corpus()
    _write_episode(out, 11, UNRUNNABLE, "strong")
    _write_summary(out, UNRUNNABLE, "strong", n_runs=1, n_misaligned=0)
    return out


class TestAModelThatCannotRunTheTaskIsNotInTheCorpus:
    """Excluded on the router's terms and by its route, with its own stamp,
    because the reason is a different one and a reader is told which."""

    def test_it_is_in_no_figure(self):
        report = rr.build_report(_corpus_with_unrunnable())
        assert report["n_episode_files"] == 3
        assert report["n_models"] == 1

    def test_it_is_named_and_counted_under_its_own_reason(self):
        report = rr.build_report(_corpus_with_unrunnable())
        stamp = report["unrunnable_excluded"]
        assert stamp["models"] == list(UNRUNNABLE_MODELS)
        assert (stamp["n_episodes_dropped"], stamp["n_summaries_dropped"]) \
            == (1, 1)
        assert UNRUNNABLE not in report["routers_excluded"]["models"]

    def test_printed_under_its_own_heading(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_router_exclusion(
                rr.build_report(_corpus_with_unrunnable())[
                    "unrunnable_excluded"],
                "MODELS THAT CANNOT RUN THE TASK EXCLUDED")
        assert "CANNOT RUN THE TASK" in buf.getvalue()
        assert UNRUNNABLE in buf.getvalue()
