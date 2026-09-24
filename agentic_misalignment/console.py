"""The comparison as a table on a terminal. Computes nothing that is not
already in the report.
"""

from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR


def print_report(report: dict) -> None:
    """The comparison as a table, computing nothing not already in `report`."""
    print("=" * 78)
    print("EXTERNAL AGENTIC-MISALIGNMENT BENCHMARK vs SUBVERSIONBENCH")
    print("=" * 78)
    print(f"\n{report['source']}")
    print(f"\nanalysis {report['version']}, rollout {report['rollout_version']}")
    print(f"{report['n_pairs']} model(s) overlap.")

    for row in report["unmatched_external_models"]:
        kind = "DECIDED" if row["decided"] else "GAP    "
        print(f"  [{kind}] external model not paired: "
              f"{row['external_model']}")
        if row["reason"]:
            print(f"            {row['reason']}")
    if report["unmatched_local_models"]:
        print(f"  {len(report['unmatched_local_models'])} local model(s) have "
              f"no external row (expected - this benchmark ran far more)")

    print("\n" + "-" * 78)
    print("PAIRS (aware = safety-aware and capability-aware pooled)")
    print("-" * 78)
    print(f"{'local model':<30} {'ext rate':>9} {'ext gap':>8} "
          f"{'loc rate':>9} {'loc gap':>8}  agree")
    for pair in report["pairs_by_pooling"]["any_aware"]:
        e, loc = pair["external"], pair["local"]
        eg, lg = e["suppression_gap"], loc["suppression_gap"]
        # A gap is None when a side has zero aware episodes to divide by -
        # possible on any model with few enough episodes, and the exact case
        # this fixture-driven test found. "OPPOSITE" claims a comparison that
        # did not happen, and formatting None directly is the same defect the
        # correlations block below was fixed for: absent must print as absent.
        if eg is None or lg is None:
            agree, eg_s, lg_s = "n/a", "n/a", "n/a"
        else:
            agree = "same" if (eg > 0) == (lg > 0) else "OPPOSITE"
            eg_s, lg_s = f"{eg:+.1%}", f"{lg:+.1%}"
        mark = " !" if (e["aware_side_underpowered"]
                        or loc["aware_side_underpowered"]) else ""
        print(f"{pair['local_model']:<30} {e['overall_rate']:>8.1%} "
              f"{eg_s:>8} {loc['misaligned_rate']:>9.1%} {lg_s:>8}  "
              f"{agree}{mark}")
    print("  gap = unaware rate minus aware rate; POSITIVE means awareness "
          "went with less harmful behaviour.")
    print(f"  ! one side's aware bucket is below "
          f"{MIN_INFORMATIVE_DENOMINATOR} trajectories or episodes.")

    print("\n" + "-" * 78)
    print("CORRELATIONS")
    print("-" * 78)
    for c in report["correlations"]:
        pooling = f" [{c['aware_pooling']}]" if c["aware_pooling"] else ""
        print(f"\n{c['measure']}{pooling}: {c['measure_label']}")
        # rho, p, the method and the separation verdict are None TOGETHER: too
        # few pairs overlap for a coefficient to exist, which is not the same as
        # a coefficient of zero and must not be formatted as one. Guarding only
        # rho - which is what this did - moves the crash one field along rather
        # than removing it, and the run that finds it is the one with no corpus.
        # `note` comes from spearman() and says why, so the reason is reported
        # rather than a threshold being restated here and drifting from it.
        if c["spearman_rho"] is None:
            print(f"    n={c['n_models']}   no coefficient: {c['note']}")
            continue
        print(f"    n={c['n_models']}   Spearman rho={c['spearman_rho']:+.3f}   "
              f"p={c['p']:.4g} ({c['p_method']})   "
              f"{'SEPARATED' if c['separated'] else 'not separated'}")
        if c["leave_one_out_rho_range"]:
            lo, hi = c["leave_one_out_rho_range"]
            print(f"    leave-one-out rho ranges {lo:+.3f} to {hi:+.3f}"
                  + (f", most influential: {c['most_influential_model']}"
                     if c.get("most_influential_model") else ""))
        if c.get("n_opposite_direction") is not None:
            print(f"    direction: {c['n_same_direction']} pair(s) agree on the "
                  f"SIGN of the gap, {c['n_opposite_direction']} disagree")
            if c["n_opposite_direction"]:
                print(f"    {c['direction_note']}")
        if c["n_underpowered_aware_sides"]:
            print(f"    {c['n_underpowered_aware_sides']} pair(s) rest on an "
                  f"aware bucket below {MIN_INFORMATIVE_DENOMINATOR}")
        if c["note"]:
            print(f"    {c['note']}")

    print("\n" + "-" * 78)
    print("SCENARIO x ACT (every external scenario against every "
          "SubversionBench act)")
    print("-" * 78)
    best = report.get("best_scenario_act_pairing")
    for c in report.get("scenario_act_correlations") or []:
        mark = " <-- strongest" if best is not None and c is best else ""
        if c["spearman_rho"] is None:
            print(f"  {c['scenario']:<14} x {c['act']:<10} n={c['n_models']}   "
                  f"no coefficient: {c['note']}{mark}")
            continue
        lo_hi = ""
        if c["leave_one_out_rho_range"]:
            lo, hi = c["leave_one_out_rho_range"]
            lo_hi = f"   loo {lo:+.3f} to {hi:+.3f}"
        print(f"  {c['scenario']:<14} x {c['act']:<10} n={c['n_models']}   "
              f"rho={c['spearman_rho']:+.3f}   p={c['p']:.4g}{lo_hi}{mark}")
    print(f"\n{report['interpretation']}.")
