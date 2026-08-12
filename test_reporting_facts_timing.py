"""
Wall-clock figures: the one group describing the RUN rather than the episodes.

Apart from the rest because a reader deciding whether to collect more needs it and a
reader interpreting a rate does not. It is also the only fact group that cannot be
computed from the run files alone - elapsed time is a property of the batch - which
is why it takes `runtime` and why a rebuild has to recover that from the previous
summary.
"""

from subversionbench.reporting.facts.timing import timing_facts


def _episode(eval_s=10.0, grader_s=2.0, total_s=12.0):
    return {"timing": {"eval_seconds": eval_s, "grader_seconds": grader_s,
                       "total_run_seconds": total_s}}


class TestTheBatchSpan:
    def test_elapsed_is_the_difference_between_the_two_clock_readings(self):
        got = timing_facts([], {"t_batch_start": 100.0, "t_batch_end": 190.0})
        assert got["total_elapsed"] == 90.0

    def test_active_time_excludes_deliberate_delay(self):
        """The delay between episodes is politeness to the provider, not work. A
        cost-per-episode computed over elapsed time would be wrong by whatever
        --delay was set to."""
        got = timing_facts([], {"t_batch_start": 0.0, "t_batch_end": 100.0,
                                "total_delay_seconds": 30})
        assert got["total_active"] == 70.0

    def test_the_delay_is_reported_as_well_as_subtracted(self):
        """Otherwise the two totals differ by an amount the reader cannot account
        for."""
        got = timing_facts([], {"t_batch_start": 0.0, "t_batch_end": 100.0,
                                "total_delay_seconds": 30})
        assert got["total_delay_seconds"] == 30

    def test_an_absent_runtime_gives_zero_rather_than_raising(self):
        """A batch summarised without a recovered runtime still has to produce a
        report; the timing section is the part that degrades, not the whole thing."""
        got = timing_facts([], {})
        assert got["total_elapsed"] == 0.0 and got["total_active"] == 0.0

    def test_the_totals_are_rounded_to_one_place(self):
        """They are written into the summary file, so full float noise would make
        two identical rebuilds compare unequal."""
        got = timing_facts([], {"t_batch_start": 0.0,
                                "t_batch_end": 1.23456789})
        assert got["total_elapsed"] == 1.2


class TestThePerEpisodeTimes:
    def test_each_series_is_collected(self):
        got = timing_facts([_episode(), _episode(eval_s=20.0)], {})
        assert got["eval_times"] == [10.0, 20.0]
        assert got["grader_times"] == [2.0, 2.0]
        assert got["run_times"] == [12.0, 12.0]

    def test_an_episode_with_no_timing_is_skipped_not_zeroed(self):
        """A missing measurement is not a fast episode. Averaging a zero in would
        drag the mean down and make a partial batch look cheaper than it was."""
        got = timing_facts([_episode(), {}], {})
        assert got["eval_times"] == [10.0]

    def test_an_empty_batch_gives_empty_series_not_none(self):
        """The console divides by len(), so None here would be a crash on the one
        path that matters least."""
        got = timing_facts([], {})
        assert got["eval_times"] == [] and got["run_times"] == []

    def test_the_series_keep_episode_order(self):
        """They are stored per run in the summary, so the order has to correspond
        to something rather than being incidental."""
        got = timing_facts([_episode(eval_s=float(i)) for i in range(5)], {})
        assert got["eval_times"] == [0.0, 1.0, 2.0, 3.0, 4.0]


class TestItIsPure:
    def test_it_does_not_mutate_what_it_is_given(self):
        import copy
        episodes = [_episode(), _episode()]
        runtime = {"t_batch_start": 0.0, "t_batch_end": 10.0}
        before = copy.deepcopy((episodes, runtime))
        timing_facts(episodes, runtime)
        assert (episodes, runtime) == before

    def test_it_reads_no_clock_of_its_own(self):
        """Every figure comes from `runtime`, so the same inputs give the same
        output - which is what makes a rebuilt summary comparable with a live one."""
        import inspect
        src = inspect.getsource(timing_facts)
        for forbidden in ("time.time", "datetime.now", "perf_counter"):
            assert forbidden not in src, forbidden
