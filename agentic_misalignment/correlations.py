"""Rank correlation between the two benchmarks, on two measures and
every (scenario, act) pairing.

Five models overlap, which is enough to report a rho and nowhere near
enough to conclude one - so every coefficient comes back with its n and
its leave-one-out range.
"""

from subversionbench.power import spearman, spearman_leave_one_out

from .bundle import ACTS, MEASURES
from .rates import external_rates_by_scenario
from .pairing import local_index


def _series(pairs: list, measure: str) -> tuple:
    """The two ranked series for one measure, and the pairs they came from."""
    if measure == "level":
        usable = [p for p in pairs
                  if p["external"]["overall_rate"] is not None
                  and p["local"]["misaligned_rate"] is not None]
        return ([p["external"]["overall_rate"] for p in usable],
                [p["local"]["misaligned_rate"] for p in usable], usable)
    usable = [p for p in pairs
              if p["external"]["suppression_gap"] is not None
              and p["local"]["suppression_gap"] is not None]
    return ([p["external"]["suppression_gap"] for p in usable],
            [p["local"]["suppression_gap"] for p in usable], usable)


def correlate(pairs: list, measure: str, pooling: str = "any_aware") -> dict:
    """
    One rank correlation, with the leave-one-out range that qualifies it.

    Spearman rather than Pearson: the two sides count different things on
    different scenarios, so only their order is comparable. At this n the
    p-value is an exact permutation p-value - see power.spearman.

    The leave-one-out range is not decoration. With five pairs a single model
    can carry a rho from strongly positive to strongly negative, and a rho
    printed without that range invites a conclusion the data cannot support.
    """
    xs, ys, usable = _series(pairs, measure)
    result = spearman(xs, ys)
    influence = spearman_leave_one_out(xs, ys)
    out = {
        "measure": measure,
        "measure_label": MEASURES[measure],
        "aware_pooling": pooling if measure == "suppression" else None,
        "n_models": len(usable),
        "spearman_rho": (round(result["rho"], 4)
                         if result["rho"] is not None else None),
        "p": result["p"],
        "p_method": result["method"],
        "separated": result["separated"],
        "note": result["note"],
        "leave_one_out_rho_range": (
            [round(influence["min_rho"], 4), round(influence["max_rho"], 4)]
            if influence["min_rho"] is not None else None),
        "models": [p["local_model"] for p in usable],
        "n_underpowered_aware_sides": sum(
            1 for p in usable
            if p["external"]["aware_side_underpowered"]
            or p["local"]["aware_side_underpowered"]),
    }
    # Rho ranks; it does not compare signs. On the suppression measure the two
    # sides can rank models identically - rho = 1 - while disagreeing about
    # whether awareness suppresses harm at all in most of them, because a rank
    # correlation is invariant to where zero sits. Direction is therefore
    # counted alongside, the mirror of the argument in
    # data_quality._measure_agreement: sign alone is not enough there, and rho
    # alone is not enough here.
    if measure == "suppression":
        signs = [(p["external"]["suppression_gap"] > 0,
                  p["local"]["suppression_gap"] > 0) for p in usable]
        agreeing = [e == loc for e, loc in signs]
        out["n_same_direction"] = sum(agreeing)
        out["n_opposite_direction"] = len(agreeing) - sum(agreeing)
        out["direction_note"] = (
            "rho ranks the models; it says nothing about whether the two "
            "benchmarks agree that awareness suppresses harm. Where these "
            "disagree, a positive rho means the ORDER matches while the effect "
            "does not.")
    index = influence.get("most_influential_index")
    if index is not None:
        out["most_influential_model"] = usable[index]["local_model"]
    return out


def scenario_act_pairs(bundle: dict, local_acts: dict, scenario: str, act: str,
                       pooling: str = "any_aware") -> list:
    """One row per (external model, local model): external's rate on ONE
    scenario paired with local's rate on ONE act - the per-(scenario, act)
    analogue of build_pairs, which pairs the pooled OVERALL row against the
    pooled misaligned_rate instead."""
    ext = external_rates_by_scenario(bundle, pooling).get(scenario, {})
    pairs = []
    for local_model, external_model in sorted(local_index(bundle).items()):
        if local_model not in local_acts or external_model not in ext:
            continue
        pairs.append({
            "local_model": local_model, "external_model": external_model,
            "external": ext[external_model], "local_act": local_acts[local_model][act],
        })
    return pairs


def scenario_act_correlations(bundle: dict, local_acts: dict,
                              pooling: str = "any_aware") -> list:
    """
    Every (external scenario, SubversionBench act) pair's rank correlation.

    write_chart's level panel already covers the pooled OVERALL row against
    the pooled misaligned_rate; this is that same question taken apart two
    ways at once instead of pooled - one scenario at a time, one act at a
    time - so a reader can see whether one scenario or one act is carrying a
    correlation the pooled numbers hide.
    """
    out = []
    for scenario in sorted(external_rates_by_scenario(bundle, pooling)):
        for act in ACTS:
            pairs = scenario_act_pairs(bundle, local_acts, scenario, act, pooling)
            usable = [p for p in pairs
                     if p["external"]["overall_rate"] is not None
                     and p["local_act"]["rate"] is not None]
            xs = [p["external"]["overall_rate"] for p in usable]
            ys = [p["local_act"]["rate"] for p in usable]
            result = spearman(xs, ys)
            influence = spearman_leave_one_out(xs, ys)
            out.append({
                "scenario": scenario, "act": act,
                "n_models": len(usable),
                "spearman_rho": (round(result["rho"], 4)
                                if result["rho"] is not None else None),
                "p": result["p"], "p_method": result["method"],
                "separated": result["separated"], "note": result["note"],
                "leave_one_out_rho_range": (
                    [round(influence["min_rho"], 4), round(influence["max_rho"], 4)]
                    if influence["min_rho"] is not None else None),
                "pairs": usable,
            })
    return out


def best_scenario_act_pairing(correlations: list) -> dict:
    """
    The strongest of scenario_act_correlations()'s rows, or None if none has
    a coefficient.

    Ranked by rho itself, not |rho|: a positive rho here means the two
    benchmarks agree on which models are worse, the same sense every other
    rho in this file is read. Not a fixed choice - which scenario and which
    act win is whatever this correlates strongest today, and can move as
    stamps get added and models get re-evaluated.
    """
    candidates = [c for c in correlations if c["spearman_rho"] is not None]
    return max(candidates, key=lambda c: c["spearman_rho"]) if candidates else None
