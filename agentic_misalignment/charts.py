"""The four figures. Losing matplotlib costs these and nothing else -
every number on them is in the printed report and in the JSON.
"""

import os

from subversionbench import charting
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR, wilson_ci

from .rates import external_rates_by_scenario


CHART_DPI = 150

# Offsets tried, in points, in priority order - up-right of the marker first,
# then an alternating up/down sweep at the same horizontal distance. Sized for
# the five points this comparison has, not the eleven sad_oversight.py's
# leaderboard chart lays out; that file's own history is the reason to keep
# this generous rather than tuned tight to today's n; a sixth or seventh
# overlapping model is the kind of change that would not touch this file.
_LABEL_OFFSETS = ((7, 4),) + tuple(
    (7, 4 + sign * step * 10) for step in range(1, 16) for sign in (1, -1))


def _place_labels(fig, ax, points: list) -> None:
    """
    One label per point, nudged off the natural offset only where it collides.

    Measured against the rendered bounding box rather than guessed from font
    size and string length - sad_oversight.py tried guessing twice on its own
    charts and got it wrong both times, which is the reason this asks
    matplotlib directly instead of repeating that history in a second file.
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
            ann = ax.annotate(text, (x, y), textcoords="offset points",
                              xytext=_LABEL_OFFSETS[-1], fontsize=7,
                              color="#333333")
            chosen = ann.get_window_extent(renderer=renderer)
        placed.append(chosen)


def write_chart(report: dict, path: str) -> str:
    """
    Two panels: the level correlation, and the suppression gap that is the
    sharper of the two claims.

    THE GAP PANEL IS THE POINT OF THIS CHART
    -----------------------------------------
    A rank correlation on the suppression gap can be strongly positive while
    the two benchmarks disagree about whether awareness suppresses harm at
    all, because rho is invariant to where zero sits - which is exactly what
    happened here (rho positive, 3 of 5 pairs opposite in sign). Dashed lines
    at zero on both axes turn that into a quadrant a reader sees directly:
    top-right and bottom-left agree on the sign of the gap, the other two
    corners disagree, and no amount of staring at a rho value shows that on
    its own.

    Wilson intervals on the level panel, none on the gap panel: a rate has a
    standard interval: a DIFFERENCE of two rates does not have one already
    computed anywhere in this file, and building one would be new statistical
    machinery for a panel that already has a more direct caution available -
    the hollow-marker flag on whichever pairs rest on an underpowered aware
    bucket, which is the actual known weak point of a gap.
    """
    plt = charting.import_pyplot("Chart")
    if plt is None:
        return None
    pairs = report["pairs_by_pooling"].get("any_aware") or []
    if not pairs:
        return None
    by_key = {(c["measure"], c["aware_pooling"]): c for c in report["correlations"]}
    level_stat = by_key[("level", None)]
    gap_stat = by_key[("suppression", "any_aware")]

    fig, (ax_level, ax_gap) = plt.subplots(1, 2, figsize=(12, 5.5))

    level_points = []
    for pair in pairs:
        e, loc = pair["external"], pair["local"]
        if e["overall_rate"] is None or loc["misaligned_rate"] is None:
            continue
        ex, lo = e["overall_rate"] * 100, loc["misaligned_rate"] * 100
        ex_ci = wilson_ci(e["harmful"], e["n"])
        lo_ci = wilson_ci(loc["misaligned"], loc["n"])
        ax_level.errorbar(
            ex, lo,
            xerr=[[ex - ex_ci[0] * 100], [ex_ci[1] * 100 - ex]],
            yerr=[[lo - lo_ci[0] * 100], [lo_ci[1] * 100 - lo]],
            fmt="o", markersize=6, capsize=2, elinewidth=1.0,
            color="#4c72b0", alpha=0.85, zorder=3)
        level_points.append((ex, lo, pair["local_model"]))
    _place_labels(fig, ax_level, level_points)
    subtitle = (f"rho={level_stat['spearman_rho']:+.2f}, "
                f"p={level_stat['p']:.3f}, n={level_stat['n_models']}"
                if level_stat["spearman_rho"] is not None else level_stat["note"])
    ax_level.set_title(f"harmful-behaviour level\n{subtitle}", fontsize=9)
    ax_level.set_xlabel("AM harmful-behaviour rate (%)", fontsize=9)
    ax_level.set_ylabel("SubversionBench misalignment rate (%)", fontsize=9)
    ax_level.grid(alpha=0.25)

    gap_points, any_underpowered = [], False
    for pair in pairs:
        e, loc = pair["external"], pair["local"]
        if e["suppression_gap"] is None or loc["suppression_gap"] is None:
            continue
        ex, lo = e["suppression_gap"] * 100, loc["suppression_gap"] * 100
        agree = (ex > 0) == (lo > 0)
        underpowered = e["aware_side_underpowered"] or loc["aware_side_underpowered"]
        any_underpowered = any_underpowered or underpowered
        ax_gap.scatter(
            ex, lo, s=44,
            facecolors=("none" if underpowered else
                       ("#4c72b0" if agree else "#c44e52")),
            edgecolors=("#4c72b0" if agree else "#c44e52"),
            linewidths=1.4, alpha=0.9, zorder=3)
        gap_points.append((ex, lo, pair["local_model"]))
    ax_gap.axhline(0, color="#999999", linestyle="--", linewidth=0.8, zorder=1)
    ax_gap.axvline(0, color="#999999", linestyle="--", linewidth=0.8, zorder=1)
    _place_labels(fig, ax_gap, gap_points)
    subtitle = (f"rho={gap_stat['spearman_rho']:+.2f}, p={gap_stat['p']:.3f}, "
                f"n={gap_stat['n_models']}, {gap_stat['n_same_direction']} agree "
                f"/ {gap_stat['n_opposite_direction']} disagree on sign"
                if gap_stat["spearman_rho"] is not None else gap_stat["note"])
    ax_gap.set_title(f"unaware-minus-aware gap\n{subtitle}", fontsize=9)
    ax_gap.set_xlabel("AM gap (points)", fontsize=9)
    ax_gap.set_ylabel("SubversionBench gap (points)", fontsize=9)
    ax_gap.grid(alpha=0.25)

    captions = [
        f"AM = the external Agentic Misalignment benchmark. "
        f"{report['n_pairs']} models overlap. Spearman rank correlation, exact "
        f"permutation p-value. DESCRIPTIVE: at this n one model's position "
        f"moves rho substantially - see the JSON for the leave-one-out range.",
        "left: error bars are 95% Wilson intervals on each rate.",
        "right: dashed lines mark zero. Top-right and bottom-left AGREE on the "
        "sign of the gap; the other two corners disagree - blue/red marks which."
        + ("  hollow: an aware bucket below "
           f"{MIN_INFORMATIVE_DENOMINATOR} trajectories or episodes on either "
           "side." if any_underpowered else ""),
        report["interpretation"] + ".",
    ]
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


def _slug(text: str) -> str:
    """Filesystem-safe stand-in for a bundle-sourced name.

    Never applied to a name written in this file - only to text read from the
    decrypted bundle at runtime, the same boundary external_rates_by_scenario
    keeps. A hardcoded scenario name in source would be exactly the plaintext
    this file's crypto exists to avoid; a slug computed from the runtime value
    is not, because it never appears in anything tracked.
    """
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


def write_scenario_charts(bundle: dict, chart_dir: str,
                          pooling: str = "any_aware") -> list:
    """
    One bar chart per external harm scenario: each model's harmful rate.

    SubversionBench has one scenario, not three, so there is nothing local to
    correlate a scenario against - these are a descriptive breakdown of the
    external benchmark's own data, not a comparison. write_chart's OVERALL
    panel is the pooled version of exactly this; these are the three scenarios
    it pools, undone, for a reader who wants to see whether they tell the same
    story or different ones.
    """
    plt = charting.import_pyplot("Chart")
    if plt is None:
        return []
    by_scenario = external_rates_by_scenario(bundle, pooling)
    paths = []
    for scenario in sorted(by_scenario):
        models = by_scenario[scenario]
        rows = sorted(
            ((m, s) for m, s in models.items() if s["overall_rate"] is not None),
            key=lambda ms: ms[1]["overall_rate"])
        if not rows:
            continue
        fig, ax = plt.subplots(figsize=(7.5, 0.45 * len(rows) + 1.8))
        ys = range(len(rows))
        for y, (_model, stats) in zip(ys, rows, strict=True):
            rate = stats["overall_rate"] * 100
            lo, hi = wilson_ci(stats["harmful"], stats["n"])
            ax.errorbar(rate, y, xerr=[[rate - lo * 100], [hi * 100 - rate]],
                        fmt="o", markersize=6, capsize=3, elinewidth=1.1,
                        color="#4c72b0", zorder=3)
            if stats["unaware"]["rate"] is not None:
                ax.scatter(stats["unaware"]["rate"] * 100, y, marker="|", s=130,
                          linewidths=1.6, color="#c44e52", zorder=4,
                          label="unaware" if y == 0 else None)
            if stats["aware"]["rate"] is not None:
                ax.scatter(stats["aware"]["rate"] * 100, y, marker="|", s=130,
                          linewidths=1.6, color="#55a868", zorder=4,
                          label="aware" if y == 0 else None)
        ax.set_yticks(list(ys))
        ax.set_yticklabels([model for model, _ in rows], fontsize=8)
        ax.set_xlim(left=0)
        ax.set_xlabel("AM harmful-behaviour rate (%)", fontsize=9)
        ax.set_title(scenario, fontsize=10)
        ax.grid(axis="x", alpha=0.25)
        if ax.get_legend_handles_labels()[1]:
            ax.legend(fontsize=7, loc="lower right")
        caption = _wrap(
            "AM = the external Agentic Misalignment benchmark. Dot + error "
            "bar: overall rate, 95% Wilson interval. Ticks: the unaware/aware "
            "split that feeds the suppression-gap correlation elsewhere in "
            "this report. Descriptive only, not compared against "
            "SubversionBench - see the JSON for n per model.")
        fig.text(0.01, 0.01, caption, fontsize=7, va="bottom", color="#555555")
        fig.tight_layout(rect=(0, 0.1, 1, 1))
        path = os.path.join(
            chart_dir, f"agentic_misalignment_scenario_{_slug(scenario)}.png")
        fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths


def write_scenario_act_chart(report: dict, path: str) -> str:
    """
    The single (external scenario, SubversionBench act) pair with the
    strongest rank correlation among every one scenario_act_correlations()
    considered.

    NOT A FIXED PAIRING. Which scenario and which act win is read off
    `report` at runtime, never chosen in source - scenario names may not sit
    in source at all (see the module docstring), and the winning pair is a
    fact about the corpus today that can move as stamps get added and models
    get re-evaluated. Same shape as write_chart's level panel - a rate
    against a rate, both with real Wilson intervals - rather than the gap
    panel's hollow-marker convention, which exists for a DIFFERENCE of rates
    that has no interval computed anywhere in this file.
    """
    plt = charting.import_pyplot("Chart")
    if plt is None:
        return None
    best = report.get("best_scenario_act_pairing")
    if not best or not best.get("pairs"):
        return None

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    points = []
    for pair in best["pairs"]:
        e, loc = pair["external"], pair["local_act"]
        ex, lo = e["overall_rate"] * 100, loc["rate"] * 100
        ex_ci = wilson_ci(e["harmful"], e["n"])
        lo_ci = wilson_ci(loc["taken"], loc["n"])
        ax.errorbar(
            ex, lo,
            xerr=[[ex - ex_ci[0] * 100], [ex_ci[1] * 100 - ex]],
            yerr=[[lo - lo_ci[0] * 100], [lo_ci[1] * 100 - lo]],
            fmt="o", markersize=7, capsize=3, elinewidth=1.1,
            color="#4c72b0", alpha=0.85, zorder=3)
        points.append((ex, lo, pair["local_model"]))
    _place_labels(fig, ax, points)

    subtitle = (f"rho={best['spearman_rho']:+.2f}, p={best['p']:.3f}, "
               f"n={best['n_models']}")
    ax.set_title(f"{best['scenario']} (AM) vs {best['act']} act "
                f"(SubversionBench)\n{subtitle}", fontsize=10)
    ax.set_xlabel(f"AM {best['scenario']} harmful-behaviour rate (%)", fontsize=9)
    ax.set_ylabel(f"SubversionBench {best['act']} act rate (%)", fontsize=9)
    ax.grid(alpha=0.25)

    captions = [
        "AM = the external Agentic Misalignment benchmark. Of every (AM "
        "scenario, SubversionBench act) pair considered, this is the one "
        "with the strongest rank correlation.",
        "error bars are 95% Wilson intervals on each rate. Descriptive, not "
        "causal: the two benchmarks are independent measurements on "
        "different scenarios, not a controlled experiment, so a "
        "correlation here does not show that either predicts or causes "
        "the other.",
    ]
    if best["leave_one_out_rho_range"]:
        lo, hi = best["leave_one_out_rho_range"]
        captions.append(
            f"leave-one-out rho ranges {lo:+.3f} to {hi:+.3f}: how far "
            f"dropping any single model could move this correlation.")
    wrapped = [_wrap(c) for c in captions]
    height_in = fig.get_size_inches()[1]
    line_in, gap_in, top_in = 0.16, 0.19, 0.11
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
