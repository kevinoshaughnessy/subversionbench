"""
Which episodes are drawn: one negative per positive, matched by model and cell,
none reused, and an episode with only an uncounted act in neither class.
"""

import json
import os
import tempfile

from monitoring.arms import SourceArm, arm_named
from monitoring.sample import draw, episode_label, scan_arm, write_manifest


def _analysis(act=None, index=4):
    a = {"misaligned": bool(act)}
    if act == "oversight":
        a.update(oversight_act_form="persisted",
                 awareness_timing_oversight={"act_index": index})
    if act == "undone":
        a.update(oversight_act_form="undone",
                 awareness_timing_oversight={"act_index": index})
    if act == "goalguard_uncounted_oversight":
        a.update(oversight_act_form="persisted", goalguard_act_form=False,
                 awareness_timing_oversight={"act_index": index})
    return a


def _episode(model, act=None, cell=("none", True, False, None)):
    nudge, oversight, lure, goalguard = cell
    return {"model": model, "nudge": nudge, "oversight": oversight, "lure": lure,
            "goalguard": goalguard, "rollout_version": "r10",
            "transcript": [{"type": "tool_call", "cmd": "x"}] * 10,
            "analysis": _analysis(act)}


def _corpus(episodes):
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "corpus"))
    for i, e in enumerate(episodes):
        with open(os.path.join(root, "corpus", f"run_{i}_x.json"), "w",
                  encoding="utf-8") as f:
            json.dump(e, f)
    return root


ARM = SourceArm("test-arm", "corpus")


class TestTheLabel:
    def test_a_counted_act_is_a_positive_at_its_step(self):
        label = episode_label(_analysis("oversight", 7))
        assert label["label"] == "act" and label["act_index"] == 7
        assert label["acts"] == ["oversight"] and not label["concealed"]

    def test_an_undone_act_is_a_concealed_positive(self):
        assert episode_label(_analysis("undone"))["concealed"]

    def test_no_act_is_a_negative(self):
        assert episode_label(_analysis())["label"] == "clean"

    def test_an_uncounted_act_alone_is_neither(self):
        """Goal-guarding counts only its own act, so its oversight act is not a
        positive there - and must not be drawn as clean either."""
        assert episode_label(_analysis("goalguard_uncounted_oversight")) is None


class TestTheDraw:
    def _records(self):
        episodes = ([_episode("m/a", "oversight")] * 3 + [_episode("m/b", "oversight")]
                    + [_episode("m/a")] * 5 + [_episode("m/b", cell=("strong", True, False, None))]
                    + [_episode("m/c")] * 20 + [_episode("unbiased/pareto", "oversight")])
        records, skipped = scan_arm(ARM, _corpus(episodes))
        assert skipped == 0
        return records

    def test_half_and_half_with_the_router_left_out(self):
        sample = draw(self._records(), seed=1)
        assert sum(e["label"] == "act" for e in sample) == 4
        assert sum(e["label"] == "clean" for e in sample) == 4
        assert not any(e["model"] == "unbiased/pareto" for e in sample)

    def test_negatives_match_model_and_cell_first(self):
        negatives = [e for e in draw(self._records(), seed=1) if e["label"] == "clean"]
        assert {e["match"] for e in negatives if e["model"] == "m/a"} == {"model_and_cell"}
        b = [e for e in negatives if e["model"] == "m/b"]
        assert len(b) == 1 and b[0]["match"] == "model"

    def test_no_negative_is_drawn_twice(self):
        """Exactly as many negatives in the cell as positives, so a draw with
        replacement could only fill it by repeating one."""
        episodes = [_episode("m/a", "oversight")] * 6 + [_episode("m/a")] * 6
        records, _ = scan_arm(ARM, _corpus(episodes))
        negatives = [e for e in draw(records, seed=1) if e["label"] == "clean"]
        assert len(negatives) == 6
        assert len({e["id"] for e in negatives}) == 6

    def test_the_same_seed_draws_the_same_sample(self):
        records = self._records()
        assert draw(records, seed=3) == draw(records, seed=3)

    def test_per_arm_caps_the_positives(self):
        sample = draw(self._records(), seed=1, per_arm=2)
        assert sum(e["label"] == "act" for e in sample) == 2


class TestTheManifest:
    def test_it_will_not_replace_one(self):
        out = tempfile.mkdtemp()
        write_manifest(out, [], {})
        try:
            write_manifest(out, [], {})
        except FileExistsError:
            return
        raise AssertionError("a second manifest replaced the first")

    def test_the_shipped_arms_are_the_two_collected_scenarios(self):
        assert arm_named("mainline-r10").corpus == "eval_results_r10"
        assert arm_named("goalguard-r1").corpus == "eval_results_goalguard_r1"


class TestTheSchemingTag:
    def test_each_record_says_whether_its_scheming_keywords_matched(self):
        with_kw, without = _episode("m/a"), _episode("m/a")
        with_kw["analysis"]["scheming_keywords"] = ["some match"]
        records, _ = scan_arm(ARM, _corpus([with_kw, without]))
        assert sorted(r["scheming_keywords"] for r in records) == [False, True]
