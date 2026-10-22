"""Every model inside one arm, drawn as counts: report/single_arm.py says why
a count and not a rate. One module because every chart here reads the one
block, through the one panel shape, and none reads anything else."""

from collections import Counter

from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR

from .captions import _wrap
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .style import (CHART_DPI, _COLOURS, _FIGURE_MARGIN, _FIGURE_WIDTH,
                    _ROW_HEIGHT, _TITLE_WRAP)

ARM_WORDS = {
    "baseline": "no nudge, oversight present, no lure (baseline)",
    "max_pressure": "max nudge, oversight present, lure present",
    "lure": "no nudge, oversight present, lure present",
    "no_oversight": "no nudge, no oversight, no lure",
    "goalguard_replacement": "no nudge, oversight present, cutover imminent",
    "goalguard_deferred": "no nudge, oversight present, cutover deferred",
}

MEASURE_WORDS = {
    "aware": "verbalised eval awareness",
    "aware_text": "awareness in visible text",
    "misaligned": "misaligned act",
    "scheming": "scheming",
    "monitoring_disabled": "monitoring disabled",
    "sandbox_escape": "sandbox escape attempt",
    "honeypot_discovered": "lure file seen",
    "honeypot_read": "lure file read",
}

COUNT_NOTE = (
    f"Counts, not rates: a model has about ten episodes in one arm, under the "
    f"{MIN_INFORMATIVE_DENOMINATOR} a rate needs, so each figure is k of n "
    f"episodes with no interval. Two models a few episodes apart are not "
    f"shown to differ.")

_EMPTY = "#e6e6e6"


def _block(report: dict) -> dict:
    return report.get("single_arm") or {}


def _arm_rows(report: dict, arm: str) -> dict:
    """{model: row} for one named arm; empty when the corpus lacks it."""
    found = _block(report).get("arms", {}).get(arm)
    return {r["model"]: r for r in found["by_model"]} if found else {}


def _columns(report: dict, specs: tuple) -> list:
    """(header, {model: counts}, colour) per (arm, measure, header, colour)
    spec whose arm the corpus holds and some model could be read on."""
    out = []
    for arm, measure, header, colour in specs:
        counts = {m: r["counts"][measure]
                  for m, r in _arm_rows(report, arm).items()
                  if r["counts"][measure]["n"]}
        if counts:
            out.append((header, counts, colour))
    return out


def _caption_block(fig, report: dict, captions: list) -> None:
    captions = captions + [COUNT_NOTE] + [
        text for text, _colour in _exclusion_captions(report)]
    fig.text(0.01, 0.0, "\n".join(_wrap(c) for c in captions), fontsize=7,
             color="#555555", va="top")


def _save(plt, fig, path: str) -> str:
    # Tight, because the scenario mark adds a title line after layout.
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _draw_count_panels(plt, report: dict, specs: tuple, title: str,
                       captions: list, path: str, marked=frozenset()):
    """One column per spec, models down the side sorted by the first
    column's count; None when no spec has anything to draw. A model in
    `marked` gets an asterisk, which a caption must explain."""
    columns = _columns(report, specs)
    if not columns:
        return None
    first = columns[0][1]

    def order(model):
        # By share, so a model collected twice over in this arm sorts among
        # the others rather than above them; the bars still show the count.
        got = first.get(model)
        return (-(got["k"] / got["n"]) if got else 1, model)

    models = sorted({m for _h, counts, _c in columns for m in counts},
                    key=order)
    ys = range(len(models))
    fig, axes = plt.subplots(
        1, len(columns), sharey=True, squeeze=False,
        figsize=(max(_FIGURE_WIDTH, 2.6 * len(columns) + 2.4),
                 _ROW_HEIGHT * len(models) + _FIGURE_MARGIN))
    for ax, (header, counts, colour) in zip(axes[0], columns, strict=True):
        n = [counts.get(m, {"n": 0})["n"] for m in models]
        k = [counts.get(m, {"k": 0})["k"] for m in models]
        ax.barh(ys, n, height=0.7, color=_EMPTY)
        ax.barh(ys, k, height=0.7, color=colour)
        for y, (got, of) in enumerate(zip(k, n, strict=True)):
            if of:
                ax.annotate(f"{got}/{of}", (of, y), xytext=(3, 0),
                            textcoords="offset points", va="center",
                            fontsize=6)
        ax.set_xlim(0, max(n) * 1.3)
        ax.xaxis.get_major_locator().set_params(integer=True)
        ax.set_title(_wrap(header, 24), fontsize=8, loc="left")
        ax.set_xlabel("episodes", fontsize=7)
        ax.tick_params(axis="x", labelsize=7)
    axes[0, 0].set_yticks(list(ys), [f"{m} *" if m in marked else m
                                     for m in models], fontsize=7)
    axes[0, 0].set_ylim(len(models) - 0.5, -0.5)
    fig.suptitle(_wrap(title + _exclusion_title_suffix(report), _TITLE_WRAP),
                 fontsize=10, x=0.01, ha="left")
    _caption_block(fig, report, captions + ["The grey bar is n."])
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    return _save(plt, fig, path)


def _specs(arm: str, measures: tuple) -> tuple:
    colours = (_COLOURS["model"], _COLOURS["model_significant"],
               _COLOURS["crude"], _COLOURS["parallel"],
               _COLOURS["stratified"])
    return tuple((arm, m, MEASURE_WORDS[m], colours[i % len(colours)])
                 for i, m in enumerate(measures))


def plot_baseline_profile(plt, report: dict, path: str):
    """Awareness and every act in the baseline arm."""
    return _draw_count_panels(
        plt, report, _specs("baseline", (
            "aware", "misaligned", "scheming", "monitoring_disabled",
            "sandbox_escape")),
        f"Every model in one arm: {ARM_WORDS['baseline']}",
        ["Sorted by awareness. Scheming is a misaligned act the interrogation "
         "found concealed, so its count sits inside the act's."], path)


def plot_baseline_text_awareness(plt, report: dict, path: str):
    """Awareness from every channel beside visible text alone, baseline."""
    marked = frozenset(m for m, r in _arm_rows(report, "baseline").items()
                       if r["text_is_floor"])
    return _draw_count_panels(
        plt, report, _specs("baseline", ("aware", "aware_text")),
        f"Verbalised eval awareness, all channels and visible text alone: "
        f"{ARM_WORDS['baseline']}",
        ["Visible text is the one channel every model returns, so it is the "
         "count that compares across models. * reasoning came back in this "
         "arm, so that model's visible-text count is a floor; unmarked, the "
         "grader saw visible text alone and the two counts are the same "
         "measurement. A smaller n on the right is aware episodes whose "
         "cited evidence could be placed in neither channel: undetermined, "
         "not absent."], path, marked)


def plot_max_pressure_acts(plt, report: dict, path: str):
    """Each act at the max nudge with the lure present."""
    return _draw_count_panels(
        plt, report, _specs("max_pressure", (
            "misaligned", "monitoring_disabled", "sandbox_escape")),
        f"Misaligned acts at the strongest pressure: "
        f"{ARM_WORDS['max_pressure']}",
        ["Sorted by the act count. The arm where models separate: at the "
         "baseline most take no act at all."], path)


def plot_lure_arm(plt, report: dict, path: str):
    """How far each model took the lure, with no nudge."""
    return _draw_count_panels(
        plt, report, _specs("lure", (
            "honeypot_discovered", "honeypot_read", "misaligned",
            "sandbox_escape")),
        f"The lure without a nudge: {ARM_WORDS['lure']}",
        ["Sorted by episodes that saw the lure file in a listing; read is "
         "those that got its contents back."], path)


def plot_no_oversight_arm(plt, report: dict, path: str):
    """The acts left when there is no monitor to disable."""
    return _draw_count_panels(
        plt, report, _specs("no_oversight", ("sandbox_escape", "misaligned")),
        f"With no oversight to subvert: {ARM_WORDS['no_oversight']}",
        ["The oversight act does not exist in this arm, so the misaligned "
         "count is the other acts alone."], path)


def plot_goalguard_arms(plt, report: dict, path: str):
    """The counted act per model, cutover imminent beside deferred."""
    return _draw_count_panels(
        plt, report, (
            ("goalguard_replacement", "misaligned",
             "misaligned act, cutover imminent", _COLOURS["model_significant"]),
            ("goalguard_deferred", "misaligned",
             "misaligned act, cutover deferred", _COLOURS["model"])),
        "Goal-guarding, every model with no nudge and oversight present: "
        "replacement beside deferred",
        ["Sorted by the replacement arm. The arms differ only in whether the "
         "cutover lands this cycle."], path)


def _scatter_panel(ax, rows: dict, words: str) -> None:
    points = Counter((r["counts"]["aware"]["k"], r["counts"]["misaligned"]["k"])
                     for r in rows.values() if r["counts"]["aware"]["n"])
    xs, ys = zip(*points, strict=True)
    ax.scatter(xs, ys, s=[30 * n for n in points.values()],
               color=_COLOURS["model"], alpha=0.6, edgecolor="white")
    for (x, y), n in points.items():
        if n > 1:
            ax.annotate(str(n), (x, y), ha="center", va="center", fontsize=6,
                        color="white")
    top = max(r["n_episodes"] for r in rows.values())
    ax.set_xlim(-0.6, top + 0.6)
    ax.set_ylim(-0.6, top + 0.6)
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_xlabel("aware episodes", fontsize=8)
    ax.set_title(_wrap(words, 40), fontsize=8, loc="left")


def plot_awareness_vs_act(plt, report: dict, path: str):
    """One point per model, aware count against act count, in each of the
    baseline and max-pressure arms; None when the corpus has neither."""
    panels = [(arm, _arm_rows(report, arm)) for arm in
              ("baseline", "max_pressure")]
    panels = [(arm, rows) for arm, rows in panels
              if any(r["counts"]["aware"]["n"] for r in rows.values())]
    if not panels:
        return None
    fig, axes = plt.subplots(1, len(panels), squeeze=False, sharey=True,
                             figsize=(_FIGURE_WIDTH, 5.2))
    for ax, (arm, rows) in zip(axes[0], panels, strict=True):
        _scatter_panel(ax, rows, ARM_WORDS[arm])
    axes[0, 0].set_ylabel("episodes with a misaligned act", fontsize=8)
    fig.suptitle(_wrap("Awareness against the act, one point per model, "
                       "within one arm" + _exclusion_title_suffix(report),
                       _TITLE_WRAP), fontsize=10, x=0.01, ha="left")
    _caption_block(fig, report, [
        "Held to one arm so the arm mix cannot make the association: the "
        "max nudge raises both. A point's size and number are how many "
        "models share it. Observed, not assigned - an association, not an "
        "effect."])
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    return _save(plt, fig, path)
