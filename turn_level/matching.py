"""
The risk sets: for each case, the control turns it is compared with.

A case is an episode's first counted act, at turn t, with the act possible from turn o, so
k = t - o turns since opportunity. Its controls are turns from other episodes of the same model
and arm, with the same act kind available, at their own o + k, that had reached that turn and
had taken no counted act before it or on it (incidence density sampling: an episode can serve
as a control in several sets, and as a case in another). An episode whose act could not be
located serves in no set, because no turn of it can be shown to come before its act.

Drawn without replacement within a set and independently across sets, from one seeded
generator consumed in a fixed order, so the same records and seed give the same sets.
"""

import collections
import random


def case_origin(record: dict) -> tuple:
    """(o, whether the act came before its own opportunity) for a case.

    An act before o is possible only if a target was written blind; the plan keeps the case with
    o set to the act turn, and counts it.
    """
    o, t = record["opportunity"].get(record["act"]["kind"]), record["act"]["turn"]
    if o is None or t < o:
        return t, True
    return o, False


def control_turn(record: dict, kind: str, k: int) -> int | None:
    """The turn at which `record` is at risk for `kind` k turns after its opportunity, or None if
    it is not eligible there: the act kind is not available, the episode had ended, or it had
    taken a counted act before that turn or takes one on it."""
    o = record["opportunity"].get(kind)
    if o is None or record["act_unlocated"]:
        return None
    turn = o + k
    if turn > record["last_turn"]:
        return None
    if record["act"] is not None and record["act"]["turn"] <= turn:
        return None
    return turn


def _pools(records: list) -> dict:
    """Records by (model, stratum), each pool in a fixed order."""
    pools = collections.defaultdict(list)
    for r in sorted(records, key=lambda r: r["key"]):
        pools[(r["model"], tuple(r["stratum"]))].append(r)
    return pools


def build_sets(records: list, group: str, n_controls: int, seed: int) -> dict:
    """Every case's matched set, and the counts the plan reports alongside them."""
    rng = random.Random(seed)
    pools = _pools(records)
    sets, counts = [], collections.Counter()
    origins = collections.defaultdict(collections.Counter)
    for case in sorted((r for r in records if r["act"] is not None), key=lambda r: r["key"]):
        kind, t = case["act"]["kind"], case["act"]["turn"]
        o, blind = case_origin(case)
        counts["act before its opportunity"] += blind
        origins[kind][o] += 1
        k = t - o
        eligible = [(r, turn) for r in pools[(case["model"], tuple(case["stratum"]))]
                    if r["key"] != case["key"]
                    and (turn := control_turn(r, kind, k)) is not None]
        if not eligible:
            counts["cases dropped, no eligible control"] += 1
            continue
        drawn = rng.sample(eligible, min(n_controls, len(eligible)))
        counts["sets with fewer controls than asked"] += len(drawn) < n_controls
        sets.append({
            "id": f"{group}-{len(sets) + 1:04d}", "kind": kind, "model": case["model"],
            "stratum": case["stratum"], "scenario": case["scenario"], "k": k,
            "case": {"episode": case["key"], "turn": t, "o": o},
            "controls": [{"episode": r["key"], "turn": turn, "o": r["opportunity"][kind]}
                         for r, turn in sorted(drawn, key=lambda d: d[0]["key"])],
        })
    counts["cases"] = len(sets) + counts["cases dropped, no eligible control"]
    counts["acts not located"] = sum(r["act_unlocated"] for r in records)
    return {"sets": sets, "counts": dict(counts),
            "opportunity_turns": {kind: dict(sorted(c.items())) for kind, c in origins.items()},
            "models_without_a_case": sorted({r["model"] for r in records}
                                            - {r["model"] for r in records if r["act"]})}


def located_fraction_by_model(records: list) -> dict:
    """model -> (episodes that acted, of them located), for the plan's listing of unlocated acts."""
    out = collections.defaultdict(lambda: [0, 0])
    for r in records:
        if r["act"] is not None or r["act_unlocated"]:
            out[r["model"]][0] += 1
            out[r["model"]][1] += r["act"] is not None
    return {m: tuple(v) for m, v in sorted(out.items())}
