"""
Each counted act by purpose and the evidence for it (D7).

The act's own record comes first, a hand label second, and an act with
neither is counted as not yet labelled - never dropped, never guessed. Purpose
never changes a count: the block covers exactly the acts act_forms counts.
"""

import io
import json
import os
import tempfile
from contextlib import redirect_stdout

import report as rr
from report.console import _print_act_purposes
from report.purposes import export_hand_labels, load_hand_labels


def _row(form="persisted", by_act=None, run_file="run_1_m_a.json",
         model="m/a", act="oversight"):
    row = {"model": model, "run_file": run_file,
           "oversight_act_form": None, "goalguard_act_form": None,
           "sandbox_act_form": None}
    row[f"{act}_act_form"] = form
    row[f"{act}_purpose_by_act"] = by_act
    return row


def _pooled(rows, hand=None):
    return rr.act_purposes(rows, hand or {})["pooled"]


class TestEachActGetsOneSource:
    def test_the_act_settles_it_first(self):
        got = _pooled([_row(by_act="evade")],
                      {"run_1_m_a.json|oversight": "test"})["oversight"]
        assert got["by_source"] == {"act": 1, "hand": 0, "unlabelled": 0}
        assert got["by_purpose"] == {"evade": {"act": 1, "hand": 0}}

    def test_a_hand_label_fills_what_the_act_leaves(self):
        got = _pooled([_row(form="attempted")],
                      {"run_1_m_a.json|oversight": "test"})["oversight"]
        assert got["by_source"]["hand"] == 1
        assert got["by_purpose"] == {"test": {"act": 0, "hand": 1}}

    def test_neither_is_counted_as_unlabelled_not_dropped(self):
        got = _pooled([_row(form="undone")])["oversight"]
        assert got == {"n_acts": 1, "by_purpose": {},
                       "by_source": {"act": 0, "hand": 0, "unlabelled": 1}}

    def test_a_hand_label_for_the_other_act_does_not_join(self):
        got = _pooled([_row(form="undone")],
                      {"run_1_m_a.json|goalguard": "protect_goals"})
        assert got["oversight"]["by_source"]["unlabelled"] == 1


class TestPurposeNeverChangesTheCount:
    def test_only_acts_taken_are_in_it(self):
        rows = [_row(by_act="evade"), _row(form=False), _row(form=None)]
        assert _pooled(rows)["oversight"]["n_acts"] == 1

    def test_it_covers_exactly_the_acts_act_forms_counts(self):
        rows = [_row(by_act="evade"), _row(form="undone"),
                _row(form="attempted"), _row(form=False)]
        forms = rr.act_forms([dict(r, nudge="strong", oversight=True,
                                   lure=False, goalguard=None) for r in rows])
        counted = sum(forms["pooled"]["oversight"][f]
                      for f in forms["forms"])
        assert _pooled(rows)["oversight"]["n_acts"] == counted

    def test_an_act_no_episode_took_is_left_out(self):
        assert set(_pooled([_row(by_act="evade")])) == {"oversight"}


class TestHandLabelsComeFromAFinishedPack:
    def _pack(self, d, rows, key):
        with open(os.path.join(d, "key.SEALED.json"), "w") as f:
            json.dump({"episodes": key}, f)
        with open(os.path.join(d, "labels.jsonl"), "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)

    def test_hand_rows_are_exported_and_act_rows_are_not(self):
        with tempfile.TemporaryDirectory() as d:
            self._pack(d, [{"id": "ep-1", "label": "test"},
                           {"id": "ep-2", "label": "evade", "source": "act"},
                           {"id": "ep-3", "label": None}],
                       [{"id": f"ep-{i}", "act": "oversight",
                         "run": f"eval_results_r10/run_{i}_m.json"}
                        for i in (1, 2, 3)])
            out = os.path.join(d, "hand.json")
            assert export_hand_labels(d, out) == 1
            assert load_hand_labels(out) == {"run_1_m.json|oversight": "test"}

    def test_no_export_yet_reads_as_no_labels(self):
        with tempfile.TemporaryDirectory() as d:
            assert load_hand_labels(os.path.join(d, "absent.json")) == {}


class TestItIsPrinted:
    def test_the_sources_and_purposes_are_shown(self):
        block = rr.act_purposes([_row(by_act="evade"), _row(form="undone")],
                                {})
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_act_purposes(block)
        text = buf.getvalue()
        assert "2 acts - 1 settled by the act, 0 hand-labelled, 1 not yet" in text
        assert "evade" in text

    def test_nothing_is_printed_without_acts(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_act_purposes(rr.act_purposes([_row(form=False)], {}))
        assert buf.getvalue() == ""
