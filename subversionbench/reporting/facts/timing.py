"""
Wall clock, and what it implies for a larger n.

Apart from the rest because it is the one group describing the RUN rather than the
episodes: how long it took, how much was deliberate delay, and what the same thing
would cost at three times the sample size. A reader deciding whether to collect more
needs it; a reader interpreting a rate does not.
"""


def timing_facts(all_results: list, runtime: dict) -> dict:
    """Wall-clock figures. Pure; reads `runtime` for what run files cannot hold."""
    t_batch_start = runtime.get("t_batch_start", 0.0)
    t_batch_end = runtime.get("t_batch_end", 0.0)
    total_delay_seconds = runtime.get("total_delay_seconds", 0)

    total_elapsed = round(t_batch_end - t_batch_start, 1)
    total_active = round(total_elapsed - total_delay_seconds, 1)

    eval_times = [r["timing"]["eval_seconds"] for r in all_results if "timing" in r]
    grader_times = [r["timing"]["grader_seconds"] for r in all_results if "timing" in r]
    run_times = [r["timing"]["total_run_seconds"] for r in all_results if "timing" in r]

    return {
        "total_delay_seconds": total_delay_seconds,
        "eval_times": eval_times,
        "grader_times": grader_times,
        "run_times": run_times,
        "total_active": total_active,
        "total_elapsed": total_elapsed,
    }
