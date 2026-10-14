"""
report/data_quality.act_rates_by_served_provider: did a backend mix matter?

mixed_served_provider_arms says an arm was answered by more than one backend.
This splits each such arm by the backend that answered most of an episode's
turns and sets each group's rates against the rest of the arm. Every test here
is about which episodes land in which group, because that is where a wrong
answer would look like a right one.
"""

import contextlib
import io
import tempfile

import report as rr
from test_analysis.report_fixtures import _write_episode


def _rates(out):
    return rr.act_rates_by_served_provider(rr.load_episodes(out))


def _by_provider(arm):
    return {p["provider"]: p for p in arm["providers"]}


class TestRatesByServingProvider:
    def test_a_backend_that_acts_every_time_is_set_against_one_that_never_does(self):
        out = tempfile.mkdtemp()
        for i in range(1, 6):
            _write_episode(out, i, "m", "max", served_by=["a"], tampered=True,
                           aware=True)
        for i in range(6, 11):
            _write_episode(out, i, "m", "max", served_by=["b"])
        (arm,) = _rates(out)
        a, b = _by_provider(arm)["a"], _by_provider(arm)["b"]
        assert (a["n_episodes"], a["n_misaligned"], a["n_aware"]) == (5, 5, 5)
        assert (b["n_episodes"], b["n_misaligned"], b["n_aware"]) == (5, 0, 0)
        # Fisher exact for 5/5 against 0/5 is 2/252.
        assert abs(a["p_vs_rest"]["misaligned"] - 2 / 252) < 1e-12
        assert a["acts"]["oversight"] == 5 and b["acts"]["oversight"] == 0

    def test_an_episode_is_counted_under_the_backend_of_most_of_its_turns(self):
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", served_turns=["b", "a", "a"])
        _write_episode(out, 2, "m", "max", served_turns=["b"])
        (arm,) = _rates(out)
        assert {p: g["n_episodes"] for p, g in _by_provider(arm).items()} \
            == {"a": 1, "b": 1}

    def test_a_tie_goes_to_the_backend_that_answered_first(self):
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", served_turns=["b", "a"])
        _write_episode(out, 2, "m", "max", served_turns=["a"])
        (arm,) = _rates(out)
        assert {p: g["n_episodes"] for p, g in _by_provider(arm).items()} \
            == {"a": 1, "b": 1}

    def test_an_arm_one_backend_served_is_not_split(self):
        out = tempfile.mkdtemp()
        for i in range(1, 4):
            _write_episode(out, i, "m", "max", served_by=["a"])
        assert _rates(out) == []

    def test_backends_are_compared_within_an_arm_never_across(self):
        """Each arm is uniform, so there is nothing to compare - although the
        two arms together were answered by two backends."""
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", served_by=["a"])
        _write_episode(out, 2, "m", "max", oversight=False, served_by=["b"])
        assert _rates(out) == []

    def test_an_episode_with_nothing_recorded_is_left_out(self):
        """Not recorded is not a backend: a non-OpenRouter route, or an
        episode collected before the field existed."""
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", served_by=["a"])
        _write_episode(out, 2, "m", "max")
        assert _rates(out) == []

    def test_it_is_in_the_data_quality_document(self):
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", served_by=["a"])
        _write_episode(out, 2, "m", "max", served_by=["b"])
        dq = rr.data_quality_facts(rr.load_episodes(out))
        assert len(dq["act_rates_by_served_provider"]) == 1


class TestThePrintedLine:
    def _printed(self, out):
        dq = rr.data_quality_facts(rr.load_episodes(out))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rr._print_data_quality(dq)
        return buf.getvalue()

    def test_an_arm_with_a_difference_is_listed(self):
        out = tempfile.mkdtemp()
        for i in range(1, 6):
            _write_episode(out, i, "m", "max", served_by=["a"], tampered=True)
        for i in range(6, 11):
            _write_episode(out, i, "m", "max", served_by=["b"])
        text = self._printed(out)
        assert "within the 1 arm(s)" in text
        assert "misaligned: a 5/5 (p=0.008), b 0/5 (p=0.008)" in text

    def test_an_arm_with_no_difference_is_counted_but_not_listed(self):
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", served_by=["a"])
        _write_episode(out, 2, "m", "max", served_by=["b"])
        text = self._printed(out)
        assert "0 of 4 backend-vs-rest comparisons at p < 0.05" in text
        assert "misaligned:" not in text
