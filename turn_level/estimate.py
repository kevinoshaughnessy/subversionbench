"""
The `estimate` step: the whole estimate as one document, written whatever it shows.

Refuses to run without the labels file and its SHA-256, which the plan has pushed before any
estimate is computed: the estimate is then made against exactly the labels that were recorded.
The decision rule reads A alone, and states its category as a finding only if the judge passed
validation. Writes estimate.json in the working directory and prints a summary; no text.
"""

import collections
import json
import os
import statistics as stats

from . import PLAN_SHA256, old_locator, readings, store
from .in_view import in_view_indices
from .statistics import ratio_of_odds_ratios
from .validation import gate, load_labels

PRIMARY_GROUPS = ("A", "B", "C")


def failures(sets_docs: dict, verdicts: dict) -> dict:
    """Per set file and view: units with no usable verdict after every attempt, and how many of
    those the provider refused, by role."""
    out = {}
    for name, doc in sets_docs.items():
        for view in store.SET_FILES[name]["views"]:
            c = collections.Counter()
            for s in doc["sets"]:
                for role, m in [("case", s["case"])] + [("control", x) for x in s["controls"]]:
                    slot = verdicts.get(store.unit_id(m["episode"], m["turn"], view)) or {}
                    if slot.get("record") is None:
                        c[f"{role} failed"] += 1
                        c[f"{role} refused"] += bool(slot.get("refused"))
            out[f"{name} {view}"] = dict(c)
    return out


def lengths_by_role(sets_docs: dict, verdicts: dict) -> dict:
    """Median in-view and own-turn text length, and the share of own turns holding reasoning."""
    out = {}
    for name in PRIMARY_GROUPS:
        by_role = collections.defaultdict(list)
        for s in (sets_docs.get(name) or {}).get("sets", []):
            for role, m in [("case", s["case"])] + [("control", x) for x in s["controls"]]:
                record = (verdicts.get(store.unit_id(m["episode"], m["turn"], "in_view")) or {}).get("record")
                if record is not None:
                    by_role[role].append(record)
        out[name] = {role: {"units": len(rs),
                            "median in-view chars": stats.median(r.get("in_view_chars") or 0 for r in rs),
                            "median own-turn chars": stats.median(r.get("current_chars") or 0 for r in rs),
                            "share with own-turn reasoning": round(
                                sum(bool(r.get("current_has_reasoning")) for r in rs) / len(rs), 4)}
                     for role, rs in by_role.items() if rs}
    return out


def reversals(sets_docs: dict, verdicts: dict) -> dict:
    """Pairs of one episode's units where the later one's in-view entries include all of the
    earlier one's, and how often the earlier was judged exposed and the later not."""
    from subversionbench.turn_context import reasoning_sent_back
    out = {}
    for name in PRIMARY_GROUPS:
        doc = sets_docs.get(name) or {"sets": [], "episodes": {}}
        turns = collections.defaultdict(set)
        for s in doc["sets"]:
            for m in [s["case"], *s["controls"]]:
                turns[m["episode"]].add(m["turn"])
        pairs = flips = 0
        for key, ts in sorted(turns.items()):
            judged = {t: r for t in ts if (r := (verdicts.get(store.unit_id(key, t, "in_view")) or {}).get("record"))}
            if len(judged) < 2:
                continue
            with open(doc["episodes"][key]["path"], encoding="utf-8") as f:
                episode = json.load(f)
            sent_back, tr = reasoning_sent_back(episode), episode.get("transcript") or []
            views = {t: set(in_view_indices(tr, t, sent_back)) for t in judged}
            for t1 in judged:
                for t2 in judged:
                    if t1 < t2 and views[t1] <= views[t2]:
                        pairs += 1
                        flips += judged[t1]["eval_aware"] and not judged[t2]["eval_aware"]
        out[name] = {"nested pairs": pairs, "exposed then not": flips}
    return out


def old_locator_exposure(sets_docs: dict):
    """Reading 4's exposure: the exploratory locator through this plan's in-view rule."""
    from blackmail_port import analyse as A
    from blackmail_port import judge_common as J
    awareness, members, index = {}, [], {}
    for name in PRIMARY_GROUPS:
        doc = sets_docs.get(name)
        if not doc:
            continue
        index.update(doc["episodes"])
        members += [(m["episode"], m["turn"]) for s in doc["sets"] for m in [s["case"], *s["controls"]]]
        if "corpus" in doc["inputs"]:
            corpus = doc["inputs"]["corpus"]
            awareness[os.path.basename(corpus.rstrip("/"))] = A.verdicts(
                J.output_path("awareness", corpus, doc["inputs"]["judgements"]), "model_awareness")
    found = old_locator.exposures(members, index, awareness)
    return lambda m: found.get((m["episode"], m["turn"]))


def sensitivity(sets_docs: dict, verdicts: dict, exposed) -> dict:
    a = sets_docs.get("A", {}).get("sets", [])
    groups = [n for n in PRIMARY_GROUPS if n in sets_docs]
    return {
        "1 earlier turns only": readings.primary(sets_docs, readings.verdict_exposure(verdicts, "earlier")),
        "2 leaving models out": readings.leaving_models_out(a, exposed),
        "3 by act kind": readings.by_field(a, exposed, "kind"),
        "3 by scenario": readings.by_field(a, exposed, "scenario"),
        "4 earlier locator": readings.primary(sets_docs, old_locator_exposure(sets_docs)),
        "5 eight controls": readings.odds_ratio(sets_docs.get("A_eight", {}).get("sets", []), exposed),
        "6 matched on opportunity": {n: readings.odds_ratio(
            readings.matched_on_opportunity(sets_docs[n]["sets"]), exposed) for n in groups},
        "7 deliberation held fixed": {n: readings.deliberation_held_fixed(sets_docs[n]["sets"], verdicts)
                                      for n in groups},
        "8 failed units bounded": {n: readings.bounds(sets_docs[n]["sets"], exposed) for n in groups},
        "9 no-oversight sandbox acts": readings.no_oversight(sets_docs, exposed),
    }


def decision(primary_a: dict, validation: dict) -> dict:
    category = primary_a.get("category")
    return {"category": category, "validated": validation["passes"],
            "finding": category if validation["passes"] else None,
            "note": None if validation["passes"] else
            "the judge did not pass validation: reported as unvalidated, no conclusion drawn"}


def document(work: str, labels_path: str, labels_sha256: str) -> dict:
    """The estimate document. Raises if the labels are missing, unhashed or incomplete."""
    labels, key = load_labels(labels_path, labels_sha256, work)
    sets_docs, verdicts = store.read_sets(work), store.read_verdicts(work)
    validation = gate(labels, key)
    exposed = readings.verdict_exposure(verdicts, "in_view")
    primary = readings.primary(sets_docs, exposed)
    episode_level = {n: readings.episode_level(sets_docs[n], verdicts)
                     for n in ("B", "C") if n in sets_docs}
    if "C" in sets_docs:
        episode_level["C, " + readings.FOCAL_MODEL] = readings.episode_level(
            sets_docs["C"], verdicts, readings.FOCAL_MODEL)
    return {
        "plan_sha256": PLAN_SHA256, "labels_sha256": labels_sha256,
        "verdicts_sha256": store.sha256(os.path.join(work, store.VERDICTS)),
        "sets_sha256": {n: store.sha256(store.sets_path(work, n)) for n in sets_docs},
        "validation": validation, "primary": primary,
        "decision on A": decision(primary.get("A", {}), validation),
        "B against C, " + readings.FOCAL_MODEL: ratio_of_odds_ratios(
            primary.get("B", {}), primary.get("C, " + readings.FOCAL_MODEL, {})),
        "episode level, glm-5.3 on the whole transcript": episode_level,
        "sensitivity": sensitivity(sets_docs, verdicts, exposed),
        "reported": {"set counts": {n: d["counts"] for n, d in sets_docs.items()},
                     "opportunity turns": {n: d["opportunity_turns"] for n, d in sets_docs.items()},
                     "located by model": {n: d["located_by_model"] for n, d in sets_docs.items()},
                     "models without a case": {n: d["models_without_a_case"] for n, d in sets_docs.items()},
                     "failures": failures(sets_docs, verdicts),
                     "lengths by role": lengths_by_role(sets_docs, verdicts),
                     "reversals": reversals(sets_docs, verdicts)},
    }


def _line(label: str, r) -> str:
    if not isinstance(r, dict) or "odds_ratio" not in r:
        return ""
    ci = r.get("ci95")
    interval = f" ({ci[0]}, {ci[1]})" if ci else ""
    extra = f"  {r['category']}" if r.get("category") else ""
    sets = f"  sets {r['informative_sets']}/{r['sets']}" if "sets" in r else ""
    return f"  {label:52} OR {r['odds_ratio']}{interval}{extra}{sets}"


def print_summary(doc: dict) -> None:
    v = doc["validation"]
    print(f"validation: {'passes' if v['passes'] else 'fails'}"
          + (f" ({'; '.join(v['reasons'])})" if v["reasons"] else "")
          + f"; A sensitivity {v['A']['sensitivity']['estimate']}, specificity {v['A']['specificity']['estimate']}")
    print("primary")
    for label, r in doc["primary"].items():
        print(_line(label, r))
    print(f"decision on A: {doc['decision on A']}")
    for section, results in doc["sensitivity"].items():
        print(section)
        flat = results if "odds_ratio" not in results else {"": results}
        for label, r in flat.items():
            for sub, rr in (r.items() if isinstance(r, dict) and "odds_ratio" not in r else [("", r)]):
                line = _line(f"{label} {sub}".strip(), rr)
                if line:
                    print(line)


def estimate(work: str, labels_path: str, labels_sha256: str) -> int:
    """The `estimate` step. Returns an exit code."""
    try:
        doc = document(work, labels_path, labels_sha256)
    except (FileNotFoundError, ValueError) as e:
        print(f"Refused: {e}")
        return 1
    store.write_json(os.path.join(work, store.ESTIMATE), doc)
    print_summary(doc)
    print(f"Written to {os.path.join(work, store.ESTIMATE)}")
    return 0
