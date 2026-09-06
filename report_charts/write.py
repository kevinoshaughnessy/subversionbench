"""The entry point: every chart this package offers, written into one
directory, and the paths it actually wrote.
"""

import os

from subversionbench import charting

from .characteristics import (plot_awareness_refusal_timing,
                              plot_encoded_payload_rate,
                              plot_eval_signal_rates,
                              plot_persistence_rate,
                              plot_persistence_within_model)
from .lure import plot_honeypot_access, plot_lure_misalignment
from .questions import plot_overview, plot_question


def write_charts(report: dict, chart_dir: str) -> list:
    """
    Every question chart plus the overview, into chart_dir.

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
    os.makedirs(chart_dir, exist_ok=True)
    written = []
    for i, section in enumerate(report.get("questions") or [], start=1):
        path = os.path.join(chart_dir, f"question_{i:02d}_{section['id']}.png")
        if plot_question(plt, i, section, path, report):
            written.append(path)
    overview = os.path.join(chart_dir, "questions_overview.png")
    if plot_overview(plt, report, overview):
        written.append(overview)
    # After the questions, mirroring where _print_characteristics prints in
    # run_report.py: a footnote to the twelve, not a thirteenth one. `.get`
    # throughout both plot_ functions, so a report built without a
    # "characteristics" key - every fixture in this test file before this
    # feature existed - draws nothing here rather than raising.
    rate_path = os.path.join(chart_dir, "persistence_rate.png")
    if plot_persistence_rate(plt, report, rate_path):
        written.append(rate_path)
    slope_path = os.path.join(chart_dir, "persistence_within_model.png")
    if plot_persistence_within_model(plt, report, slope_path):
        written.append(slope_path)
    signal_path = os.path.join(chart_dir, "eval_signal_rates.png")
    if plot_eval_signal_rates(plt, report, signal_path):
        written.append(signal_path)
    encoded_path = os.path.join(chart_dir, "encoded_payload_rate.png")
    if plot_encoded_payload_rate(plt, report, encoded_path):
        written.append(encoded_path)
    timing_path = os.path.join(chart_dir, "awareness_refusal_timing.png")
    if plot_awareness_refusal_timing(plt, report, timing_path):
        written.append(timing_path)
    # The lure arm, as two readings: what it did to misalignment, and what
    # happened to the file itself. plot_lure_misalignment writes one file per
    # oversight stratum and returns only the first, so the second is collected
    # by asking the filesystem rather than by rebuilding its name here - the
    # naming rule lives in one place that way.
    lure_path = os.path.join(chart_dir, "lure_misalignment.png")
    if plot_lure_misalignment(plt, report, lure_path):
        written.append(lure_path)
        stratum_path = lure_path.replace(".png", "_no_oversight.png")
        if os.path.exists(stratum_path):
            written.append(stratum_path)
    honeypot_path = os.path.join(chart_dir, "honeypot_access.png")
    if plot_honeypot_access(plt, report, honeypot_path):
        written.append(honeypot_path)
    return written
