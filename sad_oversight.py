#!/usr/bin/env python3
"""
An external situational-awareness leaderboard, and its correlation with the
evaluation-awareness rates measured here.

The data is a Stages Oversight (oversight class) task leaderboard from the
Situational Awareness Dataset - a third-party benchmark - transcribed from its
published table. Three prompt variants per model, each with a rank, a score with
its standard error, and a count of invalid responses.

WHY IT IS NOT PLAIN SOURCE
--------------------------
Same reason the scenario is not: a benchmark whose items and answers sit in a
public repository as plain text goes into the next training crawl, and a model
trained on it scores by recall. That harm is not ours to cause to somebody
else's benchmark, and it would also destroy the comparison this file exists to
make - a leaderboard is only informative while the models on it have not read
it.

So the table is encrypted at rest with a PUBLISHED passphrase, the same one
zip.sh uses on the result archives:

    donottrainonsubversionbench

That is a crawler barrier and nothing more. It offers no confidentiality: the
passphrase is three lines above this sentence and in two shell scripts. What it
does is put the text behind a step that bulk training-data pipelines do not
take - they ingest files, they do not derive keys. This is the move SAD itself
makes with its datasets and BIG-bench makes with canary strings.

    python sad_oversight.py --decode          # writes sad_oversight.json
    python sad_oversight.py --encode          # folds that file back in

sad_oversight.json is gitignored, so a decoded working copy cannot be committed
by accident.

WHY THE MODEL NAMES ARE IN THE BUNDLE TOO
-----------------------------------------
The mapping from that benchmark's model names to the OpenRouter IDs used here
lives inside the encrypted bundle rather than in this file. Keeping the names
out of plain source is the point; a mapping table in plaintext would put half
the leaderboard back into the crawl - the rows, without the scores.

WHAT THE CORRELATION CAN AND CANNOT SAY
---------------------------------------
Seven models overlap. That is enough to report a rank correlation and nowhere
near enough to conclude anything from one, which is why `correlate` returns the
leave-one-out range beside every rho and refuses to print a rho without its n.

Two further limits are structural rather than statistical, and both are recorded
in the output rather than left for the reader to notice:

  The two benchmarks measure different things. Stages Oversight asks a model to
  judge, from a prompt, whether it is being tested. This benchmark counts
  episodes where a model VERBALISED that judgement unprompted while doing a
  task. A model can be good at the first and silent in the second.

  The reasoning effort does not match. Every local run here goes over a route
  that accepts no reasoning parameter, so it sits at whatever that route does by
  default, while the leaderboard rows state an effort. Where the two disagree
  the pair is still used - dropping them would leave nothing - and the
  disagreement is counted in `effort_agreement`.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import run_report
from subversionbench.config import ROLLOUT_VERSION, VERSION
from subversionbench.power import (spearman, spearman_leave_one_out, wilson_ci)
from subversionbench.redaction import redact_paths

# ---------------------------------------------------------------------------
# The bundle
# ---------------------------------------------------------------------------

_BUNDLE_PATH = Path(__file__).with_name("sad_oversight.enc")
_PLAIN_PATH = Path(__file__).with_name("sad_oversight.json")

# Published on purpose - see the module docstring. Held here rather than
# imported from zip.sh's copy because a shell script is not importable, and
# duplicating one published string is better than parsing one.
BARRIER_PASSPHRASE = "donottrainonsubversionbench"

# PBKDF2 rounds. Deliberately modest: this is a speed bump for crawlers, not a
# password hash guarding a secret, and a decode that takes a visible moment on
# every import would be a cost paid for nothing.
_KDF_ROUNDS = 200000
_SALT_BYTES = 16
_TAG_BYTES = 32


def _keystream(key: bytes, length: int) -> bytes:
    """
    HMAC-SHA256 in counter mode, to `length` bytes.

    Stdlib only. Bringing in a real cipher would add a dependency to defend a
    passphrase this file publishes, which is a cost with no matching benefit.
    """
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _derive(salt: bytes) -> tuple:
    """One encryption key and one authentication key from the passphrase."""
    material = hashlib.pbkdf2_hmac(
        "sha256", BARRIER_PASSPHRASE.encode(), salt, _KDF_ROUNDS, dklen=64)
    return material[:32], material[32:]


def encrypt(payload: dict) -> str:
    """The bundle as base64 text: salt, then tag, then ciphertext."""
    plaintext = json.dumps(payload, indent=1, sort_keys=True).encode()
    salt = os.urandom(_SALT_BYTES)
    enc_key, mac_key = _derive(salt)
    stream = _keystream(enc_key, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = hmac.new(mac_key, salt + ciphertext, hashlib.sha256).digest()
    blob = base64.b64encode(salt + tag + ciphertext).decode()
    return "\n".join(blob[i:i + 76] for i in range(0, len(blob), 76)) + "\n"


def decrypt(text: str) -> dict:
    """
    The bundle, or ValueError.

    Authenticated, so a truncated or edited file says so instead of decoding to
    bytes that happen not to be JSON - which is the failure that wastes an
    afternoon.
    """
    raw = base64.b64decode("".join(text.split()))
    if len(raw) < _SALT_BYTES + _TAG_BYTES:
        raise ValueError("bundle is too short to contain a salt and a tag")
    salt = raw[:_SALT_BYTES]
    tag = raw[_SALT_BYTES:_SALT_BYTES + _TAG_BYTES]
    ciphertext = raw[_SALT_BYTES + _TAG_BYTES:]
    enc_key, mac_key = _derive(salt)
    expected = hmac.new(mac_key, salt + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("bundle failed authentication: it has been truncated, "
                         "edited, or written with a different passphrase")
    stream = _keystream(enc_key, len(ciphertext))
    return json.loads(bytes(a ^ b for a, b in zip(ciphertext, stream)))


def load_bundle(path: Path = None) -> dict:
    """The decrypted leaderboard."""
    return decrypt((path or _BUNDLE_PATH).read_text())


# ---------------------------------------------------------------------------
# Reading the bundle
# ---------------------------------------------------------------------------

VARIANTS = ("plain", "sp", "sp_large")

# What each variant's rows were collected under. Held in plain source because
# these are the benchmark's own condition names and carry no scores.
VARIANT_LABELS = {
    "plain": "plain prompt",
    "sp": "with situating prompt",
    "sp_large": "with situating prompt (large)",
}


def local_index(bundle: dict) -> dict:
    """
    Local model ID -> the leaderboard row it corresponds to.

    Built from the bundle's alias list rather than by string similarity. The two
    naming schemes have no derivable relation, and guessing gets it wrong in
    ways that flip a correlation this small. Three worked examples, all in this
    corpus: one local ID differs from a leaderboard row by a date stamp and
    scores 100% where the undated model scores 31%; one shares three of four
    name parts with a row for a different model in the same family; and one is
    the small variant of a family whose row names no size, which is not the same
    model and was briefly paired as though it were.

    Every one of those three is a SUBSTRING relationship, which is why no amount
    of care with prefixes or stems would have caught them. Only a decision per
    row does, and `deliberately_unmatched` is where the decisions against are
    written down so they cannot quietly revert.
    """
    rows = {(r["model"], r["effort"]): r for r in bundle["rows"]}
    index = {}
    for alias in bundle["aliases"]:
        row = rows.get((alias["sad_model"], alias["sad_effort"]))
        if not row:
            continue
        for local in alias["local_models"]:
            index[local] = {"row": row, "alias": alias}
    return index


def unmatched_rows(bundle: dict) -> list:
    """
    Leaderboard rows with no local counterpart.

    The guard that makes a hand-maintained mapping safe, the same role
    model_releases.missing_dates plays: it names what the table holds that the
    mapping does not, so a row is never dropped silently.
    """
    aliased = {(a["sad_model"], a["sad_effort"]) for a in bundle["aliases"]}
    return [f"{r['model']} ({r['effort']})" for r in bundle["rows"]
            if (r["model"], r["effort"]) not in aliased]


def unmatched_models(bundle: dict, models: list) -> list:
    """Local models with no leaderboard row, in the order given."""
    index = local_index(bundle)
    return [m for m in models if m not in index]


# ---------------------------------------------------------------------------
# The local side
# ---------------------------------------------------------------------------

def awareness_by_model(output_dir: str) -> dict:
    """
    Both awareness rates per model, pooled over every arm.

    `aware` is read from the model's reasoning AND its visible output;
    `text_reachable` from visible output alone. Both are carried because the
    first is not comparable across models whose routes return different amounts
    of reasoning, and the models on this leaderboard differ there - see
    grading/quote_grounding.awareness_channels. A correlation that holds on one
    and not the other is a fact about the instrument.

    Summaries give the mixed measure; the text-only numerator exists per episode
    only, so the arms are rebuilt from episodes for it.
    """
    pooled = {}
    for row in run_report.load_summaries(output_dir):
        entry = pooled.setdefault(row["model"], {
            "n_aware": 0, "n_aware_text": 0, "n": 0, "n_episodes": 0,
            "episodes_with_reasoning": 0})
        entry["n_aware"] += row["n_aware"]
        entry["n"] += row["n_awareness_resolved"]
        entry["n_episodes"] += row["n_runs"]
        entry["episodes_with_reasoning"] += row["episodes_with_reasoning"]
    for row in run_report.awareness_arm_rows(
            run_report.load_episodes(output_dir)):
        entry = pooled.get(row["model"])
        if entry is None:
            continue
        entry["n_aware_text"] += row["n_aware_text"]
    for entry in pooled.values():
        n = entry["n"]
        entry["aware_rate"] = round(entry["n_aware"] / n, 4) if n else None
        entry["text_rate"] = round(entry["n_aware_text"] / n, 4) if n else None
        entry["aware_ci95"] = list(wilson_ci(entry["n_aware"], n)) if n else None
        entry["reasoning_share"] = (
            round(entry["episodes_with_reasoning"] / entry["n_episodes"], 4)
            if entry["n_episodes"] else None)
    return pooled


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------

def build_pairs(bundle: dict, awareness: dict) -> list:
    """
    One record per local model that has a leaderboard row.

    ONE MODEL, NOT ONE ROUTE
    ------------------------
    Two local IDs can be the same model reached by different routes - this
    corpus has a pair of them - and both map to the same leaderboard row. They
    are pooled into one pair by adding their counts, because a correlation over
    eight points cannot afford to count one model twice: an independent-looking
    duplicate at an extreme moves rho and moves its p-value, and neither
    movement is evidence.
    """
    index = local_index(bundle)
    grouped = {}
    for model in sorted(awareness):
        found = index.get(model)
        if not found:
            continue
        key = (found["alias"]["sad_model"], found["alias"]["sad_effort"])
        entry = grouped.setdefault(key, {
            "sad_model": key[0], "sad_effort": key[1],
            "confidence": found["alias"].get("confidence", "exact"),
            "match_note": found["alias"].get("note"),
            "scores": {v: found["row"][v] for v in VARIANTS},
            "local_models": [], "n_aware": 0, "n_aware_text": 0, "n": 0,
            "n_episodes": 0, "episodes_with_reasoning": 0,
        })
        entry["local_models"].append(model)
        for field in ("n_aware", "n_aware_text", "n", "n_episodes",
                      "episodes_with_reasoning"):
            entry[field] += awareness[model][field]
    pairs = []
    for entry in grouped.values():
        n = entry["n"]
        if not n:
            continue
        entry["aware_rate"] = round(entry["n_aware"] / n, 4)
        entry["text_rate"] = round(entry["n_aware_text"] / n, 4)
        entry["aware_ci95"] = list(wilson_ci(entry["n_aware"], n))
        entry["text_ci95"] = list(wilson_ci(entry["n_aware_text"], n))
        entry["reasoning_share"] = (
            round(entry["episodes_with_reasoning"] / entry["n_episodes"], 4)
            if entry["n_episodes"] else None)
        entry["pooled_routes"] = len(entry["local_models"]) > 1
        pairs.append(entry)
    return sorted(pairs, key=lambda p: -p["scores"]["plain"]["score"])


# ---------------------------------------------------------------------------
# Correlating
# ---------------------------------------------------------------------------

MEASURES = {
    "aware": "verbalised evaluation awareness rate",
    "text_reachable": "evaluation awareness reachable from visible text",
}

_MEASURE_FIELD = {"aware": "aware_rate", "text_reachable": "text_rate"}


def correlate(pairs: list, variant: str, measure: str) -> dict:
    """
    One rank correlation, with the leave-one-out range that qualifies it.

    Spearman rather than Pearson: the two sides are a percentage-correct score
    and a rate of episodes, so only their order is comparable. The p-value is an
    exact permutation p-value at this n - see power.spearman.
    """
    field = _MEASURE_FIELD[measure]
    usable = [p for p in pairs if p.get(field) is not None]
    xs = [p["scores"][variant]["score"] for p in usable]
    ys = [p[field] for p in usable]
    result = spearman(xs, ys)
    influence = spearman_leave_one_out(xs, ys)
    out = {
        "variant": variant,
        "variant_label": VARIANT_LABELS[variant],
        "measure": measure,
        "measure_label": MEASURES[measure],
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
    }
    index = influence.get("most_influential_index")
    if index is not None:
        out["most_influential_model"] = usable[index]["sad_model"]
    return out


def _effort_agreement(pairs: list) -> dict:
    """
    How many pairs compare the same reasoning effort on both sides.

    Counted rather than assumed. Every local run goes over a route that accepts
    no reasoning parameter, so its effort is whatever that route defaults to,
    and the leaderboard states one - so a pair usually compares two different
    configurations of one model. That weakens the comparison and is the sort of
    thing a reader has to be told rather than left to work out.
    """
    return {
        "n_pairs": len(pairs),
        "n_local_effort_unset": sum(1 for _p in pairs),
        "note": ("Local runs are routed over an API that accepts no reasoning "
                 "parameter, so each sits at its route's default effort while "
                 "the leaderboard row states one. Pairs are used anyway - "
                 "dropping them would leave nothing to correlate - but a rho "
                 "here compares two configurations of a model, not one."),
    }


def build_report(output_dir: str, bundle: dict = None) -> dict:
    """The whole comparison: pairs, every correlation, and what was left out."""
    bundle = bundle or load_bundle()
    awareness = awareness_by_model(output_dir)
    pairs = build_pairs(bundle, awareness)
    correlations = [correlate(pairs, variant, measure)
                    for measure in MEASURES for variant in VARIANTS]
    # Repeated over the exact-confidence pairs alone, and empty when every pair
    # is already exact - as it is today. The branch stays because the failure it
    # guards against has happened once: a pair matched on a shared name stem
    # turned out to be a different model, and it sat at one end of the range
    # with a 0% rate, so it had leverage over a correlation it did not belong
    # in. If a future alias is ever less than certain, every rho is reported
    # again without it rather than resting on it.
    exact = [p for p in pairs if p["confidence"] == "exact"]
    sensitivity = ([correlate(exact, variant, measure)
                    for measure in MEASURES for variant in VARIANTS]
                   if len(exact) != len(pairs) else [])
    return {
        "version": VERSION,
        "rollout_version": ROLLOUT_VERSION,
        "output_dir": redact_paths(os.path.abspath(output_dir)),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "external_source": bundle.get("source"),
        "what_the_two_measure": bundle.get("construct_note"),
        "n_pairs": len(pairs),
        "n_leaderboard_rows": len(bundle["rows"]),
        "n_local_models": len(awareness),
        "pairs": pairs,
        "correlations": correlations,
        "correlations_exact_matches_only": sensitivity,
        "effort_agreement": _effort_agreement(pairs),
        "unmatched_leaderboard_rows": unmatched_rows(bundle),
        "unmatched_local_models": unmatched_models(bundle, sorted(awareness)),
        "deliberately_unmatched": bundle.get("deliberately_unmatched", []),
    }


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def print_report(report: dict) -> None:
    print(f"\n{'=' * 78}")
    print("External comparison: Stages Oversight leaderboard vs "
          "evaluation awareness")
    print(f"{'=' * 78}")
    print(f"{report['n_pairs']} model(s) on both, of "
          f"{report['n_leaderboard_rows']} leaderboard row(s) and "
          f"{report['n_local_models']} evaluated here")

    print(f"\n{'model':22} {'plain':>8} {'aware':>16} {'text-only':>16}")
    for pair in report["pairs"]:
        aware = f"{pair['aware_rate'] * 100:.1f}% {pair['n_aware']}/{pair['n']}"
        text = f"{pair['text_rate'] * 100:.1f}% {pair['n_aware_text']}/{pair['n']}"
        flags = []
        if pair["pooled_routes"]:
            flags.append(f"{len(pair['local_models'])} routes pooled")
        if pair["confidence"] != "exact":
            flags.append(f"{pair['confidence']} match")
        suffix = f"   [{'; '.join(flags)}]" if flags else ""
        print(f"{pair['sad_model']:22} "
              f"{pair['scores']['plain']['score']:7.2f}% "
              f"{aware:>16} {text:>16}{suffix}")

    for title, block in (("CORRELATIONS", report["correlations"]),
                         ("EXACT MATCHES ONLY",
                          report["correlations_exact_matches_only"])):
        if not block:
            continue
        print(f"\n{title}")
        for c in block:
            if c["spearman_rho"] is None:
                print(f"  {c['measure']:15} {c['variant']:9} {c['note']}")
                continue
            loo = c["leave_one_out_rho_range"]
            print(f"  {c['measure']:15} {c['variant']:9} "
                  f"rho={c['spearman_rho']:+.3f} p={c['p']:.4f} "
                  f"n={c['n_models']}"
                  + (f"  leave-one-out {loo[0]:+.3f}..{loo[1]:+.3f}"
                     if loo else ""))

    print(f"\n!! {report['effort_agreement']['note']}")
    if report["deliberately_unmatched"]:
        print("\nNOT matched, on purpose:")
        for item in report["deliberately_unmatched"]:
            print(f"  {item['local_model']}: {item['reason']}")
    if report["unmatched_leaderboard_rows"]:
        rows = report["unmatched_leaderboard_rows"]
        print(f"\n{len(rows)} leaderboard row(s) not evaluated here: "
              f"{', '.join(rows[:6])}"
              + (f" and {len(rows) - 6} more" if len(rows) > 6 else ""))


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

CHART_DPI = 150


# Offsets tried, in points, in priority order: the natural placement first -
# up and to the right of the marker - then an alternating up/down sweep at
# that same horizontal distance, stepping by roughly one label's height each
# time. A FIVE-offset version of this list was tried first and was not enough:
# kimi-k3 joining the comparison put four labels within a few percentage
# points of each other on the low-awareness cluster, and a sweep that stops
# after two steps each way runs out of room before all four clear each other.
# Thirty steps is comfortably more than this chart will ever need - each panel
# is 400+ pixels tall and a label is about 10 - so the search terminates on
# an early candidate for everything but the worst pile-up.
_LABEL_OFFSETS = ((7, 4),) + tuple(
    (7, 4 + sign * step * 10) for step in range(1, 31) for sign in (1, -1))


def _place_labels(fig, ax, points: list) -> None:
    """
    One label per point, nudged off the default offset only where it collides.

    WHY THIS EXISTS
    ----------------
    At seven or eight points, spread across a wide score range, a fixed offset
    above-right of the marker never collided. At eleven - once kimi-k3 joined
    the comparison - four labels in the low-awareness cluster started
    overlapping each other, on the exact panels a reader most needs to
    distinguish grok-4.6 from gemini-3.5-flash from llama 4 maverick.

    MEASURED, NOT ESTIMATED
    ------------------------
    Two prior collision checks in this codebase (the trends charts, twice)
    guessed a label's extent from font size and character count and got it
    wrong both times. This asks matplotlib for the rendered bounding box of the
    label actually drawn, in pixels, which is exact regardless of font,
    string length, or figure DPI.

    Sorted by y (awareness rate) rather than left to right, because two labels
    only compete for the same space when they are close in y - the axis both
    variants share - not when they are close in x, which changes per panel.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    placed = []
    for x, y, text in sorted(points, key=lambda p: -p[1]):
        chosen = None
        for dx, dy in _LABEL_OFFSETS:
            ann = ax.annotate(text, (x, y), textcoords="offset points",
                              xytext=(dx, dy), fontsize=7, color="#333333")
            box = ann.get_window_extent(renderer=renderer)
            if not any(box.overlaps(p) for p in placed):
                chosen = box
                break
            ann.remove()
        if chosen is None:
            # Every offset collided - eleven points in a score range this
            # narrow is not a case this chart can lay out cleanly by nudging.
            # Kept at the last-tried offset rather than dropped: a labelled
            # point sitting close to its neighbour is still more informative
            # than an unlabelled one.
            ann = ax.annotate(text, (x, y), textcoords="offset points",
                              xytext=_LABEL_OFFSETS[-1], fontsize=7,
                              color="#333333")
            chosen = ann.get_window_extent(renderer=renderer)
        placed.append(chosen)


def write_chart(report: dict, path: str) -> str:
    """
    One panel per prompt variant: leaderboard score against awareness rate.

    Both axes carry their uncertainty - standard error on the leaderboard score,
    a Wilson interval on the rate - because with eight points the intervals are
    most of what there is to see. A scatter of eight bare dots invites reading a
    line through them; eight crosses does not.
    """
    plt = _import_matplotlib()
    if plt is None:
        return None
    pairs = report["pairs"]
    if not pairs:
        return None
    # One column, three rows - plain on top, sp in the middle, sp_large on the
    # bottom, which is VARIANTS' own order. Not shared on either axis: sharey
    # would align the three onto one set of gridlines, but the row a reader
    # compares vertically here is a MODEL across variants, which the point
    # labels already do; the rate axis differs in range too little across
    # panels for a shared scale to earn the loss of each panel's own ticks.
    fig, axes = plt.subplots(len(VARIANTS), 1, figsize=(7.5, 14.5))
    by_key = {(c["measure"], c["variant"]): c for c in report["correlations"]}
    for ax, variant in zip(axes, VARIANTS):
        points = []
        for pair in pairs:
            score = pair["scores"][variant]
            lo, hi = pair["aware_ci95"]
            rate = pair["aware_rate"] * 100
            ax.errorbar(
                score["score"], rate,
                xerr=score["se"],
                yerr=[[rate - lo * 100], [hi * 100 - rate]],
                fmt="o", markersize=6, capsize=2, elinewidth=1.0,
                color="#c44e52" if pair["confidence"] != "exact" else "#4c72b0",
                alpha=0.85, zorder=3)
            points.append((score["score"], rate, pair["sad_model"]))
        # Labels placed only once every point on this panel is known, so each
        # can be checked against every other label on the SAME panel - the
        # collisions this exists for are between labels, and a panel's x
        # positions differ by variant, so the layout has to be per panel too.
        _place_labels(fig, ax, points)
        stat = by_key[("aware", variant)]
        subtitle = (f"rho={stat['spearman_rho']:+.2f}, p={stat['p']:.3f}"
                    if stat["spearman_rho"] is not None else stat["note"])
        ax.set_title(f"{VARIANT_LABELS[variant]}\n{subtitle}", fontsize=9)
        ax.set_xlabel("Stages Oversight score (%)", fontsize=9)
        # Every panel gets its own label now: stacked vertically, none of them
        # is a "leftmost column" a reader can assume carries it for the rest.
        ax.set_ylabel("verbalised evaluation awareness rate (%)", fontsize=9)
        ax.grid(alpha=0.25)

    text_rhos = ", ".join(
        f"{v}: {by_key[('text_reachable', v)]['spearman_rho']:+.2f}"
        for v in VARIANTS
        if by_key[("text_reachable", v)]["spearman_rho"] is not None)
    # Only claimed when there is one to claim: a legend entry for a category
    # with no members sends the reader looking for a red point that is not
    # there, and doubting the ones that are.
    inexact = [p for p in pairs if p["confidence"] != "exact"]
    captions = [
        f"{report['n_pairs']} models on both benchmarks. Spearman rank "
        f"correlation, exact permutation p-value. DESCRIPTIVE: at this n one "
        f"model's position moves rho substantially.",
        f"same correlation against awareness reachable from visible text alone "
        f"- {text_rhos}" if text_rhos else "",
        "x error bars: leaderboard standard error.  y error bars: 95% Wilson "
        "intervals." + ("  red = matched on a name stem, not exactly."
                        if inexact else ""),
        report["effort_agreement"]["note"],
    ]
    # Space is reserved for the captions FIRST, then they are laid into it from
    # the top down. Writing them at a fixed y and then calling tight_layout with
    # a reserved fraction leaves the axes floating well above the text, because
    # the two numbers are computed independently and neither knows the other.
    #
    # MEASURED IN INCHES, NOT IN FIGURE FRACTION
    # -------------------------------------------
    # tight_layout's rect is a fraction of the whole figure, and this figure's
    # height is not fixed - three stacked panels are 2.7x the height of the
    # three-across layout this reservation was first tuned against. A caption
    # written to occupy a FRACTION of the figure grows with it: the panels
    # went from 5.4in tall to 14.5in and the same fraction opened a gap of dead
    # space between the last x-axis label and the first line of text. A line
    # of 7.5pt caption text is the same physical height regardless of how tall
    # the figure around it is, so the reservation is sized in inches and only
    # converted to a fraction at the end, against this figure's ACTUAL height.
    height_in = fig.get_size_inches()[1]
    line_in, gap_in, top_in = 0.16, 0.19, 0.11
    wrapped = [_wrap(c) for c in captions if c]
    lines = sum(w.count("\n") + 1 for w in wrapped)
    reserved = (line_in * lines + gap_in * len(wrapped)) / height_in
    fig.tight_layout(rect=(0, reserved, 1, 1))
    y = reserved - top_in / height_in
    for text in wrapped:
        fig.text(0.01, y, text, fontsize=7.5, va="top", color="#555555")
        y -= (line_in * (text.count("\n") + 1) + gap_in * 0.6) / height_in
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _wrap(text: str, width: int = 150) -> str:
    import textwrap
    return "\n".join(textwrap.wrap(text, width, break_long_words=False,
                                  break_on_hyphens=False))


def _import_matplotlib():
    try:
        import matplotlib
    except ImportError:
        print("\nChart skipped: matplotlib is not installed. "
              "Install it with:\n    pip install 'subversionbench[charts]'")
        return None
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Correlate an external Stages Oversight leaderboard with "
                    "the evaluation-awareness rates measured in a results "
                    "directory.")
    parser.add_argument("--output-dir",
                        default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="results directory to analyse (default: "
                             "%(default)s)")
    parser.add_argument("--json-out", default=None,
                        help="where to write the JSON (default: "
                             "sad_oversight_correlation_<timestamp>.json "
                             "inside --output-dir)")
    parser.add_argument("--chart-dir", default=None,
                        help="where to write the chart (default: charts/ "
                             "inside --output-dir)")
    parser.add_argument("--no-charts", action="store_true",
                        help="skip the chart; every figure it draws is in the "
                             "printed output and the JSON either way")
    parser.add_argument("--decode", action="store_true",
                        help="write the leaderboard to sad_oversight.json to "
                             "edit, then re-run with --encode")
    parser.add_argument("--encode", action="store_true",
                        help="fold sad_oversight.json back into the encrypted "
                             "bundle")
    args = parser.parse_args()

    if args.decode:
        _PLAIN_PATH.write_text(json.dumps(load_bundle(), indent=2,
                                          sort_keys=True) + "\n")
        print(f"Wrote {_PLAIN_PATH.name} - edit it, then --encode")
        return 0
    if args.encode:
        if not _PLAIN_PATH.exists():
            print(f"{_PLAIN_PATH.name} does not exist; run --decode first")
            return 1
        _BUNDLE_PATH.write_text(encrypt(json.loads(_PLAIN_PATH.read_text())))
        print(f"Wrote {_BUNDLE_PATH.name}")
        return 0

    if not os.path.isdir(args.output_dir):
        parser.error(f"--output-dir {args.output_dir!r} does not exist")
    report = build_report(args.output_dir)
    if not report["n_pairs"]:
        print(f"No model in {redact_paths(args.output_dir)} appears on the "
              f"leaderboard; nothing to correlate.")
        return 1
    print_report(report)

    if not args.no_charts:
        chart_dir = args.chart_dir or os.path.join(args.output_dir, "charts")
        os.makedirs(chart_dir, exist_ok=True)
        chart = write_chart(report, os.path.join(
            chart_dir, "sad_oversight_correlation.png"))
        if chart:
            print(f"\nChart written to {redact_paths(chart)}")
            report["chart"] = redact_paths(chart)

    json_out = args.json_out or os.path.join(
        args.output_dir,
        f"sad_oversight_correlation_{time.strftime('%Y%m%dT%H%M%S')}.json")
    os.makedirs(os.path.dirname(os.path.abspath(json_out)), exist_ok=True)
    with open(json_out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote {redact_paths(json_out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
