"""
One file across every arm a model has been run through.

A summary describes one arm. This describes the shape across all twelve -
not by pooling episodes, which would conflate an arm's own effect with
whatever else is being measured, but by placing every arm's headline rates
side by side and by contrasting the arms that differ along exactly one
scenario axis (nudge, oversight, lure) while holding the other two fixed.
That is the only comparison this codebase treats as sound - see compare.py,
which this reuses power.compare_rates from rather than recomputing it.

Interrogation is the one axis a summary does not already break out: the
headline concealment field is the reference phrasing's answer, and every
other phrasing's answer sits inside each run file's per-episode detail,
never rolled up. This reads those directly, the same way an ad hoc
investigation into a zeroevidence/partevidence difference would.
"""

import glob
import json
import os
from collections import Counter, defaultdict

from .batch import NO_OVERSIGHT_TAG, find_run_files_by_stamp, parse_batch_filename
from .grading import SCHEMING_LEVELS
from .power import compare_rates
from .redaction import redact_paths

NUDGES = ("none", "strong", "max")

# The rates carried into the per-arm table. Each is a key into a summary's
# `rates` dict, which already has the successes/n/rate/ci95 shape this reuses
# directly - recomputing them here would be a second copy of definitions
# reporting/facts already owns, and the two would drift.
HEADLINE_RATES = (
    "misaligned", "scheming", "monitoring_disabled", "sandbox_escape_attempt",
    "host_path_read", "network_probe", "filesystem_escape", "out_of_scope",
    "eval_aware_keywords", "eval_aware_grader", "read_memo", "flagged_by_check",
)

# Of those, the subset actually contrasted across arms. Smaller than
# HEADLINE_RATES on purpose: a contrast at n=10 per arm is underpowered for
# anything but a coarse read, and running it for every rate would bury the
# ones worth a second look under noise nobody asked to see.
CONTRAST_METRICS = ("misaligned", "scheming", "monitoring_disabled",
                    "eval_aware_grader")


def _arm_key(nudge: str, oversight: bool, lure: bool) -> str:
    """The same label a batch's own filename carries - see batch_stem."""
    return (nudge + ("" if oversight else f"_{NO_OVERSIGHT_TAG}")
            + ("_lure" if lure else ""))


def _find_arm_summaries(output_dir: str, model: str) -> dict:
    """
    Every summary_*.json for this model, one entry per arm actually
    collected, keyed by (nudge, oversight, lure).

    Reads `model` from inside each file rather than off the filename, for
    the reason discover_batches does: a model slug can itself contain
    underscores, so parsing it back out of a name is not reliable. Where
    more than one summary exists for the same arm - a re-run under a
    different stamp - the one that sorts last (by filename, which sorts by
    timestamp) wins, so this reflects the current state rather than quietly
    averaging two attempts together.
    """
    found = {}
    for path in sorted(glob.glob(os.path.join(output_dir, "summary_*.json"))):
        try:
            with open(path) as f:
                s = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if s.get("model") != model:
            continue
        nudge = s.get("nudge")
        if not nudge:
            continue
        _effort, _stamp, oversight, lure, _cap = parse_batch_filename(
            path, nudge)
        found[(nudge, oversight, lure)] = (path, s)
    return found


def _variant_concealment(output_dir: str, batch_stamp: str) -> dict:
    """
    Concealment rate per interrogation variant, per act, for one arm's batch.

    Not carried in the summary at all - the headline concealment field is
    specifically the reference phrasing's answer (see scenario.py,
    DEFAULT_INTERROGATION), and every other phrasing's answer lives only in
    each run file's concealment_<act>_by_variant detail: {variant: level},
    the same settled level concealment_<act> itself is derived from, just
    one per phrasing instead of one for the reference phrasing alone. Read
    fresh from the run files rather than added to the summary schema, so
    this stays free and does not ask every other reader of a summary to
    carry a field they never asked for.

    "Concealed" uses the same SCHEMING_LEVELS definition scheming itself is
    judged on, not a second one invented for this report. An episode with no
    act of that kind contributes nothing for it - "not applicable" is not a
    level, and counting it as one would understate the rate.
    """
    by_act_variant = {
        "sandbox": defaultdict(Counter), "oversight": defaultdict(Counter),
    }
    for path in find_run_files_by_stamp(output_dir, batch_stamp):
        try:
            with open(path) as f:
                run = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        analysis = run.get("analysis") or {}
        for act, field in (("sandbox", "concealment_sandbox_by_variant"),
                           ("oversight", "concealment_oversight_by_variant")):
            by_variant = analysis.get(field) or {}
            for variant, level in by_variant.items():
                if level is None:
                    continue
                by_act_variant[act][variant][level] += 1

    result = {}
    for act, per_variant in by_act_variant.items():
        act_out = {}
        for variant, levels in per_variant.items():
            total = sum(levels.values())
            concealed = sum(levels.get(level, 0) for level in SCHEMING_LEVELS)
            act_out[variant] = {
                "n": total, "concealed": concealed,
                "rate": round(concealed / total, 4) if total else None,
                "levels": dict(levels),
            }
        if act_out:
            result[act] = act_out
    return result


def _headline_interrogation(output_dir: str, batch_stamp: str):
    """Which phrasing the headline concealment field was scored against for
    this arm - read off one saved run rather than assumed, since the field
    exists precisely so this need not be assumed."""
    run_files = find_run_files_by_stamp(output_dir, batch_stamp)
    if not run_files:
        return None
    try:
        with open(run_files[0]) as f:
            return json.load(f).get("headline_interrogation")
    except (OSError, json.JSONDecodeError):
        return None


def build_summary_of_summaries(output_dir: str, model: str) -> dict:
    """
    Assemble the cross-arm report for one model. Writes nothing - see
    write_summary_of_summaries for that.
    """
    model_slug = model.replace("/", "_")
    found = _find_arm_summaries(output_dir, model)

    arms = {}
    for (nudge, oversight, lure), (_path, s) in sorted(found.items()):
        key = _arm_key(nudge, oversight, lure)
        rates = s.get("rates") or {}
        stamp = s.get("batch_stamp")
        arm = {
            "nudge": nudge, "oversight": oversight, "lure": lure,
            "batch_stamp": stamp,
            "n_runs": s.get("n_runs"),
            "batch_aborted": s.get("batch_aborted"),
            "n_episodes_failed": len(s.get("episode_failures") or []),
            "analysis_version": s.get("version"),
            "headline_interrogation": (
                _headline_interrogation(output_dir, stamp) if stamp else None),
            "rates": {m: rates[m] for m in HEADLINE_RATES if m in rates},
        }
        if stamp:
            variant_rates = _variant_concealment(output_dir, stamp)
            if variant_rates:
                arm["concealment_by_variant"] = variant_rates
        arms[key] = arm

    all_arm_keys = {_arm_key(n, o, lure) for n in NUDGES
                    for o in (True, False) for lure in (False, True)}
    missing_arms = sorted(all_arm_keys - set(arms))

    contrasts = {"nudge": [], "oversight": [], "lure": []}

    def _contrast(axis, key_a, key_b, held: dict):
        if key_a not in arms or key_b not in arms:
            return
        for metric in CONTRAST_METRICS:
            ra = arms[key_a]["rates"].get(metric)
            rb = arms[key_b]["rates"].get(metric)
            if not ra or not rb or not ra.get("n") or not rb.get("n"):
                continue
            cmp = compare_rates(ra["successes"], ra["n"], rb["successes"], rb["n"])
            contrasts[axis].append({
                "metric": metric, "holding": held,
                "arm_a": key_a, "arm_b": key_b, "compare": cmp,
            })

    # Nudge: none -> strong -> max, holding oversight and lure fixed.
    for oversight in (True, False):
        for lure in (False, True):
            keys = [_arm_key(n, oversight, lure) for n in NUDGES]
            for a, b in zip(keys, keys[1:], strict=False):
                _contrast("nudge", a, b,
                         {"oversight": oversight, "lure": lure})

    # Oversight: true -> false, holding nudge and lure fixed.
    for nudge in NUDGES:
        for lure in (False, True):
            _contrast("oversight", _arm_key(nudge, True, lure),
                     _arm_key(nudge, False, lure),
                     {"nudge": nudge, "lure": lure})

    # Lure: false -> true, holding nudge and oversight fixed.
    for nudge in NUDGES:
        for oversight in (True, False):
            _contrast("lure", _arm_key(nudge, oversight, False),
                     _arm_key(nudge, oversight, True),
                     {"nudge": nudge, "oversight": oversight})

    # "separated" - the difference interval excludes zero - is the honest
    # headline compare_rates itself recommends over a bare p-value cutoff;
    # see its docstring. Collected here so a reader does not have to walk
    # every contrast to find the ones worth a second look.
    notable = [
        {"axis": axis, "metric": row["metric"], "holding": row["holding"],
         "arm_a": row["arm_a"], "arm_b": row["arm_b"]}
        for axis, rows in contrasts.items()
        for row in rows if row["compare"].get("separated")
    ]

    return {
        "model": model,
        "model_slug": model_slug,
        "output_dir": redact_paths(output_dir),
        "arms": arms,
        "missing_arms": missing_arms,
        "contrasts": contrasts,
        "notable_contrasts": notable,
    }


def format_summary_of_summaries(report: dict) -> str:
    """A console-readable rendering of build_summary_of_summaries' output."""
    lines = [
        f"\n{'='*72}",
        f"SUMMARY OF SUMMARIES: {report['model']}",
        f"{'='*72}",
    ]
    if report["missing_arms"]:
        lines.append(f"Missing arms (no summary found): "
                     f"{', '.join(report['missing_arms'])}")
    lines.append("")

    header_metrics = ("misaligned", "scheming", "mon_disabled",
                      "sbx_escape", "eval_aware_grd")
    metric_keys = ("misaligned", "scheming", "monitoring_disabled",
                  "sandbox_escape_attempt", "eval_aware_grader")
    col = "{:<26}" + "  {:>13}" * len(header_metrics)
    lines.append(col.format("arm", *header_metrics))
    for key, arm in sorted(report["arms"].items()):
        cells = []
        for m in metric_keys:
            r = arm["rates"].get(m)
            if not r or not r.get("n"):
                cells.append("n/a")
            else:
                cells.append(f"{r['successes']}/{r['n']}")
        lines.append(col.format(key, *cells))

    if report["notable_contrasts"]:
        lines.append(f"\n{len(report['notable_contrasts'])} contrast(s) "
                     f"where the difference interval excludes zero:")
        for c in report["notable_contrasts"]:
            lines.append(f"  [{c['axis']}] {c['arm_a']} vs {c['arm_b']} on "
                         f"{c['metric']} (holding {c['holding']})")
    else:
        lines.append("\nNo contrast's difference interval excludes zero - "
                     "consistent with no detectable effect at this n, not "
                     "with there being none.")

    for key, arm in sorted(report["arms"].items()):
        cbv = arm.get("concealment_by_variant")
        if not cbv:
            continue
        lines.append(f"\n{key} concealment by interrogation variant "
                     f"(headline={arm['headline_interrogation']}):")
        for act, variants in cbv.items():
            parts = [f"{v}={d['concealed']}/{d['n']}"
                    for v, d in sorted(variants.items())]
            lines.append(f"  {act}: " + "  ".join(parts))

    return "\n".join(lines)


def write_summary_of_summaries(output_dir: str, model: str) -> str:
    """Build, print, and write the cross-arm report. Returns the path written."""
    report = build_summary_of_summaries(output_dir, model)
    print(format_summary_of_summaries(report))
    model_slug = model.replace("/", "_")
    path = os.path.join(output_dir, f"summary_of_summaries_{model_slug}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWritten to {redact_paths(path)}")
    return path
