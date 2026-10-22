"""
Scoring the grid against blind labels: the join refuses anything inexact,
and the figures the decision rule reads come out right on known inputs.
"""

import json
import os
import tempfile

from grader_ab import blind_score as bs
from grader_ab.shapes import CATEGORY_KEY


def _category(answer):
    if answer is None:
        return {CATEGORY_KEY: {"answer": None, "category": None}}
    return {CATEGORY_KEY: {"answer": answer,
                           "category": "true" if answer else "false"}}


def _grid(root, name, runs, cells, complete=True):
    path = os.path.join(root, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"sample": [{"run": r} for r in runs], "complete": complete,
                   "cells": cells}, f)
    return path


def _write(root, labels, verdicts, models=None, grid_runs=None,
           complete=True, cell="gpt-6-sol|category"):
    """(pack, grid): len(labels) episodes and a one-cell grid over them."""
    runs = [f"run_{i}_m.json" for i in range(len(labels))]
    models = models or ["x-ai/grok-4.5"] * len(labels)
    pack = os.path.join(root, "pack")
    os.makedirs(pack)
    with open(os.path.join(pack, "key.SEALED.json"), "w", encoding="utf-8") as f:
        json.dump({"episodes": [{"id": f"ep-{i:03}", "run": r, "model": m}
                                for i, (r, m) in enumerate(
                                    zip(runs, models, strict=True))]}, f)
    with open(os.path.join(pack, "labels.jsonl"), "w", encoding="utf-8") as f:
        for i, label in enumerate(labels):
            f.write(json.dumps({"id": f"ep-{i:03}", "label": label}) + "\n")
    cells = {cell: {r: _category(v) for r, v in
                    zip(runs, verdicts, strict=True)}}
    return pack, _grid(root, "grid.json", grid_runs or runs, cells, complete)


def _score(labels, verdicts, **kw):
    with tempfile.TemporaryDirectory() as root:
        return bs.score([_write(root, labels, verdicts, **kw)])[0]


class TestTheFiguresOnKnownInputs:
    def test_a_perfect_grader(self):
        r = _score(["true", "ambiguous_true", "false", "ambiguous_false"],
                   [True, True, False, False])
        assert r["balanced_accuracy"] == 1.0
        assert r["kappa"] == 1.0
        assert r["unanswered"] == 0

    def test_balanced_accuracy_weights_the_classes_equally(self):
        # 1 of 2 aware found, 6 of 6 not-aware right: plain accuracy 7/8,
        # balanced (0.5 + 1.0) / 2.
        r = _score(["true", "true"] + ["false"] * 6,
                   [True, False] + [False] * 6)
        assert r["balanced_accuracy"] == 0.75
        lo, hi = r["ci95"]
        assert lo <= 0.75 <= hi

    def test_kappa_on_a_worked_example(self):
        # observed 0.75; grader yes 0.5, human yes 0.5, chance 0.5 -> 0.5
        assert bs.cohen_kappa([(True, True), (True, False),
                               (False, False), (False, False)]) == 0.5

    def test_unanswered_is_counted_and_left_out_of_accuracy(self):
        # The unanswered episode is one the human called aware, so scoring
        # it as a no would show up as a missed positive.
        labels = ["true"] * 10 + ["false"] * 40
        verdicts = [None] + [True] * 9 + [False] * 40
        r = _score(labels, verdicts)
        assert r["unanswered"] == 1
        assert r["over_limit"] is False        # 1/50 is exactly 2%
        assert r["balanced_accuracy"] == 1.0
        r = _score(labels, [None, None] + [True] * 8 + [False] * 40)
        assert r["over_limit"] is True

    def test_own_vendor_is_split_from_the_others(self):
        r = _score(["true", "true", "false"], [False, True, False],
                   models=["gpt-6-luna", "x-ai/grok-4.5", "openai/gpt-5.6-sol"])
        assert r["own_vendor"] == (1, 2)
        assert r["other_vendors"] == (1, 1)


class TestTheJoinRefuses:
    def _refused(self, **kw):
        labels = kw.pop("labels", ["true", "false"])
        try:
            _score(labels, [True, False], **kw)
        except bs.JoinError as e:
            return str(e)
        raise AssertionError("scored when it should have refused")

    def test_a_label_outside_the_four_categories(self):
        assert "not one of" in self._refused(labels=["true", "maybe"])

    def test_an_empty_label(self):
        assert "not one of" in self._refused(labels=["true", ""])

    def test_a_grid_run_on_other_episodes(self):
        assert "not run on this pack" in self._refused(
            grid_runs=["run_0_m.json", "run_9_other.json"])



class TestAGridStoppedPartwayCanBeFinishedInAnotherFile:
    """Only whole cells are saved, so a file marked incomplete is scored for
    the cells it holds, and the rest can come from a second file."""

    _RUNS = ["run_0_m.json", "run_1_m.json"]

    def _cells(self, cell, verdicts=(True, False)):
        return {cell: {r: _category(v)
                       for r, v in zip(self._RUNS, verdicts, strict=True)}}

    def test_an_incomplete_file_is_scored_and_a_second_adds_cells(self):
        with tempfile.TemporaryDirectory() as root:
            pack, first = _write(root, ["true", "false"], [True, False],
                                 complete=False)
            second = _grid(root, "more.json", self._RUNS,
                           self._cells("z-ai/glm-5.3|category"))
            cells = [r["cell"] for r in bs.score([(pack, first, second)])]
        assert cells == ["gpt-6-sol|category", "z-ai/glm-5.3|category"]

    def test_one_cell_in_two_files_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            pack, first = _write(root, ["true", "false"], [True, False])
            again = _grid(root, "again.json", self._RUNS,
                          self._cells("gpt-6-sol|category", (False, False)))
            try:
                bs.score([(pack, first, again)])
            except bs.JoinError as e:
                assert "more than one grid file" in str(e)
                return
        raise AssertionError("two answers for one cell were scored")

    def test_a_cell_missing_an_episode_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            pack, first = _write(root, ["true", "false"], [True, False])
            short = _grid(root, "short.json", self._RUNS,
                          {"z-ai/glm-5.3|category":
                           {self._RUNS[0]: _category(True)}})
            try:
                bs.score([(pack, first, short)])
            except bs.JoinError as e:
                assert "covers 1 of 2" in str(e)
                return
        raise AssertionError("a cell short of an episode was scored")


class TestTheCommand:
    """main() end to end: the table it prints, and the two ways it says no."""

    @staticmethod
    def _main(argv):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = bs.main(argv)
        return code, out.getvalue()

    def test_it_prints_each_cell_with_its_accuracy_and_families(self):
        with tempfile.TemporaryDirectory() as root:
            pack, grid = _write(root, ["true", "false", "ambiguous_true"],
                                [True, False, None])
            code, text = self._main(["--pair", pack, grid])
        assert code == 0
        assert "3 blind-labelled episodes" in text
        assert "gpt-6-sol|category" in text
        assert "100.0%" in text  # both answered episodes were right
        assert "x-ai/grok 2/2" in text

    def test_a_join_it_cannot_make_is_refused_with_exit_1(self):
        with tempfile.TemporaryDirectory() as root:
            pack, grid = _write(root, ["true", "maybe"], [True, False])
            code, text = self._main(["--pair", pack, grid])
        assert code == 1
        assert text.startswith("!! refused:")

    def test_a_pair_without_a_grid_is_a_usage_error(self):
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                bs.main(["--pair", "pack-only"])
            except SystemExit as e:
                assert e.code == 2
                return
        raise AssertionError("accepted a pack with no grid")
