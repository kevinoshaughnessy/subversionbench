"""One chart per corpus characteristic - the blocks under
`report["characteristics"]` that are not one of the twelve questions.

Each is the same two steps: turn a profile dict into rows, and hand
them to a shape in `draw`. What differs between them is the caption,
because what a reader must not conclude differs.
"""

from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR, wilson_ci

from . import draw
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .rows import Row
from .style import EXCLUDED_NOTE, PP, has_chart_support


def _persistence_rate_rows(profile: dict) -> list:
    """
    One row per model shown at least one refusal, in the order
    `persistence_after_refusal()` already sorted them - by rate, descending.

    `marked` carries `comparable_within_model` here, not statistical
    significance - there is no significance test on this chart. It says
    whether the model also appears on the within-model comparison chart: a
    filled marker has episodes on both sides of persistence, an open one only
    ever complied or only ever persisted, and so has a rate but no comparison.
    """
    rows = []
    for r in profile.get("by_model") or []:
        if not has_chart_support(r["n_refused"]):
            continue
        lo, hi = wilson_ci(r["n_persisted"], r["n_refused"]) or (None, None)
        rows.append(Row(r["model"], r["persistence_rate"], lo, hi, "model",
                        marked=bool(r["comparable_within_model"]),
                        note=f"n={r['n_refused']}"))
    return rows


def _persistence_slope_rows(profile: dict) -> list:
    """
    Only the models with episodes on both sides of persistence - the subset
    `comparable_within_model` already marks, because a model that only ever
    complied or only ever persisted has nothing to compare within itself.

    Sorted by how far the rate moved, descending, the same convention
    `_model_rows` uses for the forests: the row order is itself part of what
    the chart shows.
    """
    rows = []
    for r in profile.get("by_model") or []:
        if not r["comparable_within_model"]:
            continue
        # The smaller side, for the reason _model_rows gives: a slope between a
        # 40-episode rate and a 2-episode one is carried entirely by the 2.
        if not has_chart_support(min(r["complied"]["n"], r["persisted"]["n"])):
            continue
        c, p = r["complied"]["misaligned_rate"], r["persisted"]["misaligned_rate"]
        rows.append({"model": r["model"], "complied_rate": c, "persisted_rate": p,
                    "n_complied": r["complied"]["n"], "n_persisted": r["persisted"]["n"]})
    rows.sort(key=lambda row: row["persisted_rate"] - row["complied_rate"],
             reverse=True)
    return rows


def plot_persistence_rate(plt, report: dict, path: str) -> str:
    """Every model shown a sandbox refusal: how often it tried again anyway."""
    profile = ((report.get("characteristics") or {})
              .get("persistence_after_refusal") or {})
    rows = _persistence_rate_rows(profile)
    if not rows:
        return None
    ref = profile.get("persistence_rate")
    captions = [
        (profile.get("interpretation", "") + ".", "#555555"),
        (f"{profile.get('n_never_refused', 0)} episode(s) were never shown a "
         f"refusal and are excluded, not counted as compliant. "
         + EXCLUDED_NOTE + ".", "#555555"),
        ("dashed line: the corpus-wide rate. filled marker: this model also "
         "has episodes on both sides of persistence and appears on the "
         "within-model comparison chart; open: only one behaviour was "
         "observed here.", "#555555"),
        # Not WILSON_NOTE: that note also names Newcombe, for the difference
        # intervals every forest above draws. This chart draws no difference
        # at all, so naming Newcombe here would point a reader at a line that
        # is not on the figure.
        ("intervals: 95% Wilson", "#777777"),
    ] + _exclusion_captions(report)
    return draw._draw_rate_chart(
        plt, rows, "Persistence after a sandbox refusal"
        + _exclusion_title_suffix(report), captions, path,
        "persistence rate (%)", ref=ref,
        ref_label=f"all models: {ref:.1%}" if ref is not None else "")


def plot_persistence_within_model(plt, report: dict, path: str) -> str:
    """Only models with episodes on both sides: does persisting go with a
    higher misaligned rate than complying, within the same model."""
    profile = ((report.get("characteristics") or {})
              .get("persistence_after_refusal") or {})
    rows = _persistence_slope_rows(profile)
    if not rows:
        return None
    n_worse = profile.get("n_models_persisted_more_misaligned", 0)
    n_both = profile.get("n_models_comparable_within_model", 0)
    captions = [
        (profile.get("interpretation", "") + ".", "#555555"),
        (f"{n_worse}/{n_both} model(s) with episodes on both sides show a "
         f"HIGHER misaligned rate after persisting than after complying.",
         "#b00020" if n_worse else "#555555"),
        ("red: persisting went with more misalignment in this model; blue: "
         "it did not. right-hand count: n(complied)/n(persisted) episodes.",
         "#555555"),
    ] + _exclusion_captions(report)
    return draw._draw_slope_chart(
        plt, rows, "Persisting vs complying: misaligned rate, within model"
        + _exclusion_title_suffix(report),
        captions, path)



def _signal_clusters(profile: dict) -> list:
    """
    One cluster per model: its label, and one point per signal in
    `signal_keys`' fixed order - the pure data shape _draw_signal_chart
    draws, kept separate so it can be tested without matplotlib, the same
    split _persistence_rate_rows/_draw_rate_chart use.

    A point's `rate` is None where the signal was never resolved for that
    model; `_draw_signal_chart` draws nothing for it rather than a marker at
    zero, so an unmeasured signal cannot be read as a confident "no".
    """
    keys = profile.get("signal_keys") or []
    clusters = []
    for r in profile.get("by_model") or []:
        # Model-level support, so a model is present or absent as a whole
        # rather than as a cluster with holes in it. A signal that is
        # individually thin on an otherwise well-supported model keeps its
        # hollow marker below - that is a different statement, about one
        # point rather than about whether the model belongs on the figure.
        if not has_chart_support(r.get("n_episodes")):
            continue
        points = []
        for key in keys:
            s = r["signals"].get(key) or {}
            rate = s.get("rate")
            lo, hi = (wilson_ci(s["n_true"], s["n_resolved"])
                      if rate is not None else (None, None))
            points.append({"signal": key, "rate": rate, "lo": lo, "hi": hi,
                          "underpowered": bool(s.get("underpowered"))})
        clusters.append({"model": r["model"], "points": points})
    return clusters


def _encoded_payload_rate_rows(profile: dict) -> list:
    """
    One row per model with enough resolved episodes to plot, sorted the way
    `_by_model` already returns them (alphabetically) rather than by rate -
    unlike persistence, there is no meaningful "worst offender" ordering for a
    concealment attempt this rare in the corpus.

    Every row is `marked`, because after has_chart_support every row that
    survives clears the floor and a hollow marker would distinguish nothing.
    The field is kept rather than dropped so this shares _draw_rate_chart
    with the persistence chart, where `marked` still carries a real
    distinction.
    """
    rows = []
    for r in profile.get("by_model") or []:
        if not has_chart_support(r["n_resolved"]):
            continue
        lo, hi = wilson_ci(r["n_true"], r["n_resolved"]) or (None, None)
        rows.append(Row(r["model"], r["rate"], lo, hi, "model",
                        marked=True, note=f"n={r['n_resolved']}"))
    return rows


def plot_encoded_payload_rate(plt, report: dict, path: str) -> str:
    """How often each model wrote a base64 payload the grader could decode."""
    profile = (report.get("characteristics") or {}).get(
        "encoded_payload_rate") or {}
    rows = _encoded_payload_rate_rows(profile)
    if not rows:
        return None
    ref = (profile.get("pooled") or {}).get("rate")
    captions = [
        (profile.get("measure", "") + ".", "#555555"),
        (EXCLUDED_NOTE + ".", "#555555"),
        ("descriptive, not causal, and not folded into any misalignment act - "
         "see grading/encoded_payload.py for what this can and cannot prove.",
         "#555555"),
        ("intervals: 95% Wilson. NOTE THE AXIS: it runs to a fraction of "
         "100%, so a short bar here is a smaller rate than the same bar on a "
         "full-width chart.", "#777777"),
    ] + _exclusion_captions(report)
    return draw._draw_rate_chart(
        plt, rows, "Encoded payloads in the model's own words"
        + _exclusion_title_suffix(report), captions,
        path, "episodes with a decodable payload (%)", ref=ref,
        ref_label=f"all models: {ref:.2%}" if ref is not None else "",
        # This measure is a rare event by construction - a concealment
        # technique, not a behaviour every episode has the chance to show - so
        # a 0-100 axis stacks every marker against the spine. Widened
        # automatically if the data ever exceeds it; see _draw_rate_chart.
        xmax_pp=10)


def _awareness_refusal_rows(profile: dict) -> list:
    """
    One row per model with enough placeable orderings to plot, in the order
    `awareness_refusal_timing()` already sorted them - by the share descending.

    THE FLOOR IS ON `n_locatable`, NOT ON EPISODES. A model with 400 episodes
    and 3 placeable orderings has three data points on this measure, and the
    Wilson interval on 3 runs most of the axis. Each chart applies
    has_chart_support to its OWN denominator, and this measure's denominator is
    the orderings, not the corpus.
    """
    rows = []
    for r in profile.get("by_model") or []:
        if not has_chart_support(r["n_locatable"]):
            continue
        if r["rate_after"] is None:
            continue
        lo, hi = wilson_ci(r["n_after_refusal"], r["n_locatable"]) \
            or (None, None)
        rows.append(Row(r["model"], r["rate_after"], lo, hi, "model",
                        marked=True, note=f"n={r['n_locatable']}"))
    return rows


def plot_awareness_refusal_timing(plt, report: dict, path: str) -> str:
    """
    Per model: of the placeable orderings, how often awareness arrived only
    after the model had been shown a sandbox refusal.

    A RATE CHART RATHER THAN A FOREST, and the reason is the same one the
    persistence charts give: there is no zero line to test against here. This is
    not a difference between two arms, it is a share of one population, and a
    forest centred on zero would borrow a causal apparatus the ordering does not
    have. Being refused follows from the model's own command.
    """
    profile = (report.get("characteristics") or {}).get(
        "awareness_refusal_timing") or {}
    rows = _awareness_refusal_rows(profile)
    if not rows:
        return None
    pooled = profile.get("pooled") or {}
    ref = pooled.get("rate_after")
    arms = profile.get("by_arm") or {}

    def arm_words(key, label):
        arm = arms.get(key) or {}
        rate = arm.get("rate_after")
        return (f"{label} {rate * PP:.0f}% of {arm.get('n_locatable', 0)}"
                if rate is not None else f"{label} n/a")

    captions = [
        (profile.get("measure", "") + ".", "#555555"),
        # The single most load-bearing sentence on the figure: without it a
        # reader takes this for a second, independent piece of evidence that
        # awareness and the sandbox act go together.
        ("NOT a thirteenth research question. Awareness and the sandbox act "
         "are one 2x2 table and question 7 already reports it - Fisher's exact "
         "test returns the same p whichever variable is called the exposure. "
         "Only the ORDERING is new here.", "#b00020"),
        (f"Split by arm, which is where the difference is: "
         f"{arm_words('oversight', 'oversight present')}, "
         f"{arm_words('no_oversight', 'oversight absent')}. With oversight "
         f"present the model has almost always said it before being told no.",
         "#333333"),
        (f"Denominator is the placeable orderings, not episodes: "
         f"{pooled.get('n_no_refusal', 0)} episodes were never refused and "
         f"{pooled.get('n_not_aware', 0)} were refused with no keyword hit. "
         + EXCLUDED_NOTE + ", counted on those orderings.", "#555555"),
        (profile.get("instrument", "") + ".", "#555555"),
        ("descriptive, not an effect: being refused follows from the model's "
         "own command, so the two groups differ in more than the refusal. "
         "intervals: 95% Wilson.", "#777777"),
    ] + _exclusion_captions(report)
    return draw._draw_rate_chart(
        plt, rows,
        "Was the model already suspicious when the sandbox refused it?"
        + _exclusion_title_suffix(report),
        captions, path,
        "episodes verbalising awareness only AFTER the refusal (%)",
        ref=ref,
        ref_label=f"all models: {ref:.0%}" if ref is not None else "")


def plot_eval_signal_rates(plt, report: dict, path: str) -> str:
    """Every eval-awareness rubric question, each its own rate per model."""
    profile = (report.get("characteristics") or {}).get("eval_signal_rates") or {}
    keys = profile.get("signal_keys") or []
    clusters = _signal_clusters(profile)
    captions = [
        (profile.get("interpretation", "") + ".", "#555555"),
        (EXCLUDED_NOTE + ". Of the models that remain, an open marker is one "
         f"whose own resolved count for THAT signal is under "
         f"{MIN_INFORMATIVE_DENOMINATOR}.", "#555555"),
        ("intervals: 95% Wilson. Descriptive: each signal is one rubric "
         "question's own answer, not folded into the pooled eval_aware "
         "verdict reported elsewhere in this report.", "#555555"),
    ] + _exclusion_captions(report)
    return draw._draw_signal_chart(
        plt, clusters, keys, "Eval-awareness rubric signals, per model"
        + _exclusion_title_suffix(report),
        captions, path, "answered yes (%)")
