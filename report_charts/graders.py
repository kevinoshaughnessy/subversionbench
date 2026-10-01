"""The charts that put several graders' verdicts on one axis.

Every other chart here is one grader's, in that grader's own directory. These
four answer the question those cannot: does a finding depend on which model
graded it? Each row carries one marker per grader, side by side, in a colour
per grader.

THE REPORTS MUST SHARE ONE CORPUS. Each is built with
`build_report(..., paired_with=graders)`, so every grader's figures come from
the episodes ALL of them have read. Built from each grader's own report
instead, a gap between two markers would be partly which models each grader
had reached, and the chart would present a coverage difference as a
disagreement.

Nothing is computed here: every number is one grader's report, drawn beside
another's.
"""

import os

from subversionbench import charting

from .captions import _divergence_caption, _wrap
from .characteristics import _signal_clusters
from .draw import _BelowAxes
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .labels import arm_labels
from .questions import overview_rows
from .rows import Row, _model_rows, _pooled_rows
from .style import (CHART_DPI, PP, WILSON_NOTE, _FIGURE_MARGIN,
                    _FIGURE_WIDTH, _MODEL_MARKER, _ROW_HEIGHT,
                    _SUMMARY_MARKER, _TITLE_WRAP)

# Where they go, beside the per-grader directories rather than inside one:
# they belong to no single grader.
GRADER_COMPARISON_DIR = "grader_comparison"

# The questions drawn per model. Question 2 has awareness as its OUTCOME, so
# it shows the graders' rates differing directly; question 5 has it as the
# EXPOSURE, so it shows whether the awareness-misalignment link survives a
# change of grader.
QUESTIONS = ("oversight_vs_awareness", "awareness_vs_misalignment")

# One colour per grader, assigned in sorted-grader order so a grader keeps its
# colour on every chart of one run. Distinct from the kind colours in
# style._COLOURS on purpose: here the colour means WHO, not what kind of row.
_GRADER_COLOURS = ("#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e")

_POOLED = ("crude", "stratified")
# Matched on these rather than on whichever rows the first grader happens to
# have: a grader whose strata were all uninformative has no stratified row, and
# classifying by its rows alone filed the other grader's among the models.
_POOLED_LABELS = ("CRUDE POOLED", "STRATIFIED (MH)")
# A different shape per estimator, because colour already says WHICH GRADER. A
# row where one grader has a stratified estimate and another fell back to the
# crude one otherwise shows two identical diamonds, read as two graders'
# readings of one estimate when they are two estimators.
_POOLED_MARKERS = {"crude": "s", "stratified": _SUMMARY_MARKER}


def _colours(graders: list) -> dict:
    return {g: _GRADER_COLOURS[i % len(_GRADER_COLOURS)]
            for i, g in enumerate(graders)}


def _paired_caption(reports: dict) -> str:
    any_report = next(iter(reports.values()))
    return (f"every grader's figures are over the same "
            f"{any_report['n_episode_files']} episodes, the ones all of "
            f"{', '.join(reports)} have read; a gap between two markers is "
            f"the graders disagreeing, not covering different models")


def _draw_by_grader(plt, groups: list, colours: dict, title: str,
                    captions: list, path: str, xlabel: str,
                    rates: bool = False, row_height: float = _ROW_HEIGHT) -> str:
    """One row per group, one marker per grader within it.

    `groups` is a list of (label, {grader: Row or None}); a label with no
    points is drawn as a bold header, which is how the signal chart names the
    model its rows belong to. A grader with no Row for a group draws nothing
    there - an absent estimate, never a zero.
    """
    k = len(colours)
    spread = 0.28 if k > 1 else 0.0
    offsets = {g: (spread * (2 * i / (k - 1) - 1) if k > 1 else 0.0)
               for i, g in enumerate(colours)}
    height = _FIGURE_MARGIN + row_height * max(len(groups), 1) * 1.4
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, height))
    ys = list(range(len(groups) - 1, -1, -1))
    for y, (_label, points) in zip(ys, groups, strict=True):
        for grader, row in (points or {}).items():
            yy = y - offsets[grader]
            if row is None or row.diff is None:
                # Said, not left blank: an empty sub-row reads as a zero
                # nobody drew rather than as an estimate that does not exist.
                ax.text(0, yy, f"  {grader}: "
                        f"{(row.missing if row else '') or 'no estimate'}",
                        va="center", fontsize=6, color="#999999",
                        style="italic")
                continue
            colour = colours[grader]
            summary = row.kind in _POOLED
            # DEMOTED: a crude estimate its own question says not to report,
            # because crude and stratified diverge - see rows.Row. Hollow,
            # faint and dashed, but in the grader's colour rather than grey:
            # here colour is the only thing saying whose estimate it is.
            if row.lo is not None and row.hi is not None:
                ax.plot([row.lo * PP, row.hi * PP], [yy, yy], color=colour,
                        linewidth=1.8 if summary else 1.2,
                        alpha=0.35 if row.demoted else 0.8,
                        linestyle="--" if row.demoted else "-",
                        solid_capstyle="round", zorder=3)
            ax.plot([row.diff * PP], [yy],
                    marker=(_POOLED_MARKERS.get(row.kind, _SUMMARY_MARKER)
                            if summary else _MODEL_MARKER),
                    markersize=7 if summary else 5, color=colour,
                    alpha=0.5 if row.demoted else 1.0,
                    markerfacecolor=(colour if row.marked and not row.demoted
                                     else "white"),
                    markeredgecolor=colour, markeredgewidth=1.2, zorder=4)
    if rates:
        ax.set_xlim(0, 100)
    else:
        ax.axvline(0, color="#333333", linewidth=1.0, linestyle="--",
                   alpha=0.7, zorder=1)
    ax.set_yticks(ys)
    ax.set_yticklabels([label for label, _p in groups], fontsize=8)
    for tick, (_label, points) in zip(ax.get_yticklabels(), groups,
                                      strict=True):
        if points is None:
            tick.set_fontweight("bold")
    ax.set_ylim(-0.8, len(groups) - 0.2)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_title(_wrap(title, _TITLE_WRAP), fontsize=10, loc="left")
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()

    from matplotlib.lines import Line2D
    below = _BelowAxes(fig, ax, height)
    kinds = {r.kind for _label, points in groups for r in (points or {}).values()
             if r is not None and r.diff is not None}
    below.legend([Line2D([], [], color=c, marker=_MODEL_MARKER, markersize=6,
                         markerfacecolor=c, label=g)
                  for g, c in colours.items()]
                 + [Line2D([], [], color="#666666", linestyle="",
                           marker=_POOLED_MARKERS[k], markersize=6,
                           markerfacecolor="white", label=name)
                    for k, name in (("crude", "crude pooled"),
                                    ("stratified", "stratified (MH)"))
                    if k in kinds])
    for caption, colour in captions:
        below.caption(caption, colour)
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def overview_groups(reports: dict) -> list:
    """Every question's headline estimate, once per grader.

    Matched on the row label with its divergence mark removed, since one
    grader's estimates can diverge on a question where another's do not; the
    mark is kept on the group if ANY grader's diverge.
    """
    by_grader = {g: overview_rows(r)[0] for g, r in reports.items()}
    order, groups = [], {}
    for grader, rows in by_grader.items():
        for row in rows:
            base = row.label.removesuffix("  *")
            if base not in groups:
                order.append(base)
                groups[base] = {"flagged": False, "points": {}}
            groups[base]["flagged"] |= row.label.endswith("  *")
            groups[base]["points"][grader] = row
    return [(base + ("  *" if groups[base]["flagged"] else ""),
             groups[base]["points"]) for base in order]


def question_groups(question_id: str, reports: dict) -> list:
    """One question's per-model and pooled rows, once per grader.

    Models in the order of the FIRST grader's effect, so the chart reads as
    that grader's forest with the others laid over it; pooled rows last. The
    stratified row's label carries its stratum count, which can differ
    between graders, so it is matched without it.
    """
    per_grader = {}
    for grader, rep in reports.items():
        section = next((q for q in rep.get("questions") or []
                        if q["id"] == question_id), None)
        if section is None or section.get("collapsed_by_exclusion") or \
                section.get("out_of_scope_for_corpus"):
            return []
        rows = _model_rows(section.get("by_model") or []) + [
            r for r in _pooled_rows(section) if r.kind in _POOLED]
        per_grader[grader] = {
            ("STRATIFIED (MH)" if r.kind == "stratified" else r.label): r
            for r in rows}
    labels = []
    for rows in per_grader.values():
        labels += [label for label in rows if label not in labels]
    models = [lab for lab in labels if lab not in _POOLED_LABELS]
    pooled = [lab for lab in _POOLED_LABELS if lab in labels]
    return [(lab, {g: rows.get(lab) for g, rows in per_grader.items()})
            for lab in models + pooled]


def signal_groups(reports: dict) -> list:
    """Per model, a bold header and then one row per rubric signal.

    A model is drawn only where every grader's report has chart support for
    it, so no model appears under one grader and not another.
    """
    clusters = {g: {c["model"]: c for c in _signal_clusters(
        (r.get("characteristics") or {}).get("eval_signal_rates") or {})}
        for g, r in reports.items()}
    shared = set.intersection(*(set(c) for c in clusters.values()))
    groups = []
    for model in sorted(shared):
        groups.append((model, None))
        signals = [p["signal"] for p in next(iter(clusters.values()))[model]
                   ["points"]]
        for i, signal in enumerate(signals):
            points = {}
            for grader, by_model in clusters.items():
                p = by_model[model]["points"][i]
                points[grader] = Row(signal, p["rate"], p["lo"], p["hi"],
                                     marked=not p["underpowered"])
            groups.append((f"  {signal}", points))
    return groups


def _common_captions(reports: dict) -> list:
    return [(_paired_caption(reports), "#333333"),
            ("filled = significant after Holm correction for a model, "
             "interval excluding zero for a pooled estimate", "#555555"),
            (WILSON_NOTE, "#777777")] + _exclusion_captions(
                next(iter(reports.values())))


def write_grader_comparison_charts(reports: dict, chart_dir: str) -> list:
    """Every chart, each naming the scenario its corpus ran - see
    charting.scenario_marked."""
    with charting.scenario_marked(next(iter(reports.values()), {}).get("scenario")):
        return _write_grader_comparison_charts(reports, chart_dir)


def _write_grader_comparison_charts(reports: dict, chart_dir: str) -> list:
    """The four comparison charts, into chart_dir. Needs two graders or more.

    `reports` maps each grader to its report built with
    paired_with=<every grader in the mapping>.
    """
    plt = charting.import_pyplot()
    if plt is None or len(reports) < 2:
        return []
    os.makedirs(chart_dir, exist_ok=True)
    colours = _colours(sorted(reports))
    reports = {g: reports[g] for g in colours}
    any_report = next(iter(reports.values()))
    suffix = _exclusion_title_suffix(any_report)
    vs = " vs ".join(reports)
    written = []

    groups = overview_groups(reports)
    if groups:
        written.append(_draw_by_grader(
            plt, groups, colours,
            f"All research questions by grader: {vs}" + suffix,
            _common_captions(reports) + [
                ("stratified estimate where a question has one, crude "
                 "where it does not; * the two diverge for at least one "
                 "grader", "#b00020")],
            os.path.join(chart_dir, "questions_overview.png"),
            "difference in rate, percentage points (exposed minus unexposed)"))

    ids = [q["id"] for q in any_report.get("questions") or []]
    for question_id in QUESTIONS:
        groups = question_groups(question_id, reports)
        if not groups or question_id not in ids:
            continue
        index = ids.index(question_id) + 1
        section = any_report["questions"][index - 1]
        label_a, label_b = arm_labels(section)
        # The report's own warning, once per grader it applies to - the red
        # line the single-grader chart carries, which a demoted marker alone
        # cannot say.
        divergence = [(f"{g}: {_divergence_caption(r['questions'][index - 1])}",
                       "#b00020") for g, r in reports.items()
                      if _divergence_caption(r["questions"][index - 1])]
        written.append(_draw_by_grader(
            plt, groups, colours,
            f"Q{index}. {section['question']} By grader: {vs}" + suffix,
            _common_captions(reports) + divergence,
            os.path.join(chart_dir, f"question_{index:02d}_{question_id}.png"),
            f"difference in rate, percentage points ({label_a} minus "
            f"{label_b})"))

    groups = signal_groups(reports)
    if groups:
        written.append(_draw_by_grader(
            plt, groups, colours,
            f"Eval-awareness rubric signals per model, by grader: {vs}"
            + suffix,
            [(_paired_caption(reports), "#333333"),
             ("filled = the grader resolved enough episodes on that signal to "
              "be informative; open = fewer", "#555555"),
             ("intervals: 95% Wilson", "#777777")]
            + _exclusion_captions(any_report),
            os.path.join(chart_dir, "eval_signal_rates.png"),
            "answered yes (%)", rates=True, row_height=_ROW_HEIGHT * 0.6))
    return written
