"""
Twelve fixed research questions, answered from a results directory.

Run it as `python3 -m report`. This file is the command line and the assembly:
which questions the report holds, in what order, and what the document around
them says. The questions themselves, the statistics they are built from and the
printing all live in the sibling modules - `report/__init__.py` says which
module holds what.

Questions 1-10 are answered four ways: the crude pooled effect across every
episode in --output-dir, the model-stratified effect (Mantel-Haenszel, with a
Breslow-Day homogeneity test), per-model consistency with multiplicity
correction, and how the effect moves under the other manipulated axes named in
the question. Questions 11-12 are paired and are appended after that loop rather
than being made to carry fields that do not apply to them.
"""

import argparse
import json
import os
import time

import report_charts
from subversionbench.config import ROLLOUT_VERSION, VERSION
from subversionbench.redaction import redact_paths

from .console import (_print_data_quality, _print_question,
                      _print_variant_question)
from .data_quality import data_quality_facts
from .loading import awareness_arm_rows, load_episodes, load_summaries
from .pooling import _crude_vs_stratified, _models
from .questions_arms import (question_nudge_vs_awareness,
                             question_oversight_vs_awareness,
                             question_oversight_vs_misalignment,
                             question_oversight_vs_scheming)
from .questions_awareness import (question_awareness_vs_misalignment,
                                  question_awareness_vs_monitoring_disabled,
                                  question_awareness_vs_oversight_scheming,
                                  question_awareness_vs_sandbox_escape,
                                  question_awareness_vs_sandbox_scheming,
                                  question_awareness_vs_scheming)
from .questions_paired import (question_evidence_vs_concealment,
                               question_paraphrase_vs_concealment)


def build_report(output_dir: str) -> dict:
    summaries = load_summaries(output_dir)
    episodes = load_episodes(output_dir)
    # Arms rebuilt from episodes, carrying the text-only awareness numerator no
    # summary field holds. Questions 2 and 4 take the headline measure from the
    # summaries as before and this alongside it; see _text_reachable_block.
    arm_rows = awareness_arm_rows(episodes)
    questions = [
        question_oversight_vs_scheming(summaries),
        question_oversight_vs_awareness(summaries, arm_rows),
        question_oversight_vs_misalignment(summaries),
        question_nudge_vs_awareness(summaries, arm_rows),
        question_awareness_vs_misalignment(episodes, summaries),
        question_awareness_vs_monitoring_disabled(episodes),
        question_awareness_vs_sandbox_escape(episodes),
        question_awareness_vs_scheming(episodes),
        question_awareness_vs_oversight_scheming(episodes),
        question_awareness_vs_sandbox_scheming(episodes),
    ]
    # Attached here rather than inside each question: it reads three fields
    # every question already has, so building it once centrally keeps the ten
    # question functions from each carrying the same four lines - and keeps
    # _stratified from being computed twice per question.
    for section in questions:
        section["crude_vs_stratified"] = _crude_vs_stratified(
            section["overall"], section["stratified"], section["by_model"])

    # Questions 11-12 are a different shape - a list of paired contrasts rather
    # than one contrast with strata - so they are appended after the loop above
    # rather than being made to carry fields that do not apply to them. A paired
    # contrast is already within-model, so there is no stratified counterpart to
    # attach: see the Paired comparison section of power.py.
    questions.extend([
        question_paraphrase_vs_concealment(episodes),
        question_evidence_vs_concealment(episodes),
    ])
    return {
        "version": VERSION,
        "rollout_version": ROLLOUT_VERSION,
        "output_dir": redact_paths(os.path.abspath(output_dir)),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_summary_files": len(summaries),
        "n_episode_files": len(episodes),
        "n_models": len(_models(summaries)),
        "data_quality": data_quality_facts(episodes, summaries),
        "questions": questions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        # Named, because argparse otherwise takes it from argv[0] -
        # which under `-m` is `__main__.py`, a name that appears nowhere
        # a reader could act on. This is the command the docs give.
        prog="python3 -m report",
        description="Answer twelve fixed research questions from a results "
                    "directory: oversight/nudge vs scheming and verbalised "
                    "evaluation awareness, and awareness vs misalignment, "
                    "oversight-override, sandbox-escape, the three scheming "
                    "(act-plus-concealment) rates, and the two interrogation "
                    "phrasing axes against concealment.")
    parser.add_argument("--output-dir", default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="results directory to analyse (default: %(default)s)")
    parser.add_argument("--json-out", default=None,
                        help="where to write the JSON report (default: "
                             "research_report_<timestamp>.json inside "
                             "--output-dir)")
    parser.add_argument("--chart-dir", default=None,
                        help="where to write the question charts (default: "
                             "charts/ inside --output-dir)")
    parser.add_argument("--no-charts", action="store_true",
                        help="skip the charts; every figure they draw is in "
                             "the printed output and the JSON either way")
    args = parser.parse_args()

    if not os.path.isdir(args.output_dir):
        parser.error(f"--output-dir {args.output_dir!r} does not exist")

    report = build_report(args.output_dir)
    if not report["n_summary_files"]:
        print(f"No summary files found in {redact_paths(args.output_dir)}.")
        return 1

    print(f"Analysing {redact_paths(args.output_dir)}: "
          f"{report['n_summary_files']} summary file(s), "
          f"{report['n_episode_files']} episode file(s), "
          f"{report['n_models']} model(s).")
    _print_data_quality(report["data_quality"])
    for section in report["questions"]:
        # "contrasts" is the paired-question shape; the others carry "overall".
        if "contrasts" in section:
            _print_variant_question(section)
        else:
            _print_question(section)

    # Before the JSON is written, so `charts` lands in the file rather than
    # describing an artefact the report has no record of.
    if not args.no_charts:
        chart_dir = args.chart_dir or os.path.join(args.output_dir, "charts")
        written = report_charts.write_charts(report, chart_dir)
        if written:
            print(f"\n{len(written)} chart(s) written to "
                  f"{redact_paths(chart_dir)}:")
            for path in written:
                print(f"  {os.path.basename(path)}")
            report["charts"] = [redact_paths(p) for p in written]

    # NOT run_report_*.json: that name sits inside load_episodes' own
    # `run_*.json` glob, so the default output would land in the namespace this
    # script scans and be re-read as a candidate episode on the next run. It is
    # skipped today only because a report has no "model" key - the same
    # bare-prefix collision find_run_files documents three prior instances of.
    json_out = args.json_out or os.path.join(
        args.output_dir, f"research_report_{time.strftime('%Y%m%dT%H%M%S')}.json")
    os.makedirs(os.path.dirname(os.path.abspath(json_out)), exist_ok=True)
    with open(json_out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {redact_paths(json_out)}")
    return 0

# No `if __name__ == "__main__"` here. __main__.py is the entry point, and
# it says why: the package re-exports main(), so running THIS module with -m
# would execute it a second time and warn about it above every report.
