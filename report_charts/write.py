"""The entry point: every chart this package offers, written into one
directory, and the paths it actually wrote.
"""

import os

from subversionbench import charting

from .characteristics import (plot_awareness_confidence,
                              plot_awareness_refusal_timing,
                              plot_encoded_payload_rate,
                              plot_eval_signal_rates,
                              plot_misuse_profile,
                              plot_persistence_rate,
                              plot_persistence_within_model)
from .lure import plot_honeypot_access, plot_lure_misalignment
from .questions import (plot_awareness_kind_comparison, plot_overview,
                        plot_question)

# WHICH CHARTS NO GRADER'S VERDICT REACHES. They read the act keys, the
# commands and the files - never the awareness rubric, the interrogation
# labels, or a concealment or scheming verdict - so every grader would draw
# them identically, and they are drawn once per corpus instead of once per
# grader. Drawn per grader they were not even identical: each grader's report
# leaves out the episodes it has not read, so the act-rate charts under one
# grader silently showed fewer episodes than the corpus holds.
#
# Questions by id rather than position, because position is the filename and
# is decided by the report. A question not named here is drawn per grader,
# which is the safe default: a chart wrongly in that set is merely duplicated.
GRADER_FREE_QUESTIONS = frozenset({
    "oversight_vs_misalignment", "lure_vs_sandbox_escape", "goalguard_vs_act",
})

# Every chart after the questions: (filename, plot function, reads a grader
# verdict). The flag is a claim about what the plot reads, and
# test_report_graders.TestTheChartsNoGraderReaches holds it against the report
# sections each one draws from.
CHARACTERISTIC_CHARTS = (
    ("questions_overview.png", plot_overview, True),
    ("awareness_kind_comparison.png", plot_awareness_kind_comparison, True),
    ("persistence_rate.png", plot_persistence_rate, False),
    ("persistence_within_model.png", plot_persistence_within_model, False),
    ("eval_signal_rates.png", plot_eval_signal_rates, True),
    ("awareness_confidence.png", plot_awareness_confidence, True),
    ("misuse_profile.png", plot_misuse_profile, True),
    ("encoded_payload_rate.png", plot_encoded_payload_rate, False),
    ("awareness_refusal_timing.png", plot_awareness_refusal_timing, True),
    ("lure_misalignment.png", plot_lure_misalignment, False),
    ("honeypot_access.png", plot_honeypot_access, False),
)


def write_charts(report: dict, chart_dir: str, grader_dependent=None) -> list:
    """Every chart, each naming the scenario its corpus ran - see
    charting.scenario_marked."""
    with charting.scenario_marked(report.get("scenario")):
        return _write_charts(report, chart_dir, grader_dependent)


def _write_charts(report: dict, chart_dir: str, grader_dependent=None) -> list:
    """
    Every question chart plus the overview, into chart_dir.

    `grader_dependent` narrows to one kind: True for the charts that read a
    grader's verdicts, False for the ones no grader reaches - see
    GRADER_FREE_QUESTIONS. None writes both, for a caller with one report.

    Numbered by position in the report rather than by id, so the filenames sort
    into the order the questions are asked and a reader can pair a chart with a
    section of the printed output without a lookup.

    THE FILENAMES DO NOT CHANGE WHEN AN ARM IS EXCLUDED. That is deliberate and
    is why run_report writes the two readings into different directories: a
    reader comparing the arm-excluded chart with the full-corpus one wants the
    same name in two places, not a name they have to translate. What keeps them
    apart once a file leaves its directory is the title and the caption every
    chart carries - see _exclusion_captions.
    """
    plt = charting.import_pyplot()
    if plt is None:
        return []

    def wanted(reads_grader: bool) -> bool:
        return grader_dependent is None or grader_dependent == reads_grader

    os.makedirs(chart_dir, exist_ok=True)
    written = []
    for i, section in enumerate(report.get("questions") or [], start=1):
        if not wanted(section["id"] not in GRADER_FREE_QUESTIONS):
            continue
        path = os.path.join(chart_dir, f"question_{i:02d}_{section['id']}.png")
        if plot_question(plt, i, section, path, report):
            written.append(path)
    # After the questions, mirroring where _print_characteristics prints in
    # run_report.py: a footnote to the twelve, not a thirteenth one. `.get`
    # throughout the plot_ functions, so a report built without a
    # "characteristics" key draws nothing here rather than raising.
    for name, plot, reads_grader in CHARACTERISTIC_CHARTS:
        if not wanted(reads_grader):
            continue
        path = os.path.join(chart_dir, name)
        if plot(plt, report, path):
            written.append(path)
            # plot_lure_misalignment writes one file per oversight stratum and
            # returns only the first, so the second is collected by asking the
            # filesystem rather than by rebuilding its name here - the naming
            # rule lives in one place that way.
            stratum = path.replace(".png", "_no_oversight.png")
            if plot is plot_lure_misalignment and os.path.exists(stratum):
                written.append(stratum)
    return written
