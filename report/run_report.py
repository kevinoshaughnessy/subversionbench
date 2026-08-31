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

from .console import (_print_arm_exclusion, _print_characteristics,
                      _print_data_quality, _print_question,
                      _print_variant_question)
from .characteristics import characteristics
from .data_quality import data_quality_facts
from .loading import (ARM_EXCLUSIONS, EXCLUDE_NO_OVERSIGHT, NO_EXCLUSION,
                      act_arm_rows, awareness_arm_rows, exclude_arm,
                      load_episodes, load_summaries)
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


def _artefact_suffix(exclusion: str) -> str:
    """
    What to append to the chart directory and the JSON filename.

    DERIVED FROM THE EXCLUSION'S OWN NAME rather than tabulated beside it. A
    second dict keyed by the same strings is a second thing to keep in step,
    and the failure it produces is the one this naming exists to prevent: an
    exclusion added later, with no entry in the table, silently writing its
    charts over the full-corpus ones.
    """
    if exclusion not in ARM_EXCLUSIONS:
        raise ValueError(f"unknown arm exclusion {exclusion!r}")
    return "" if exclusion == NO_EXCLUSION else f"_excluding_{exclusion}"


def _collapsed_by_exclusion(section: dict, axis: str) -> str:
    """
    Whether dropping an arm left this question with only one side, and so
    nothing to contrast.

    TWO CONDITIONS, AND THE SECOND IS THE ONE THAT WAS MISSING. An empty side is
    necessary but not sufficient: a question can lose a side because the corpus
    never held that level at all. Measured on a fixture carrying two nudge
    levels but not `none`, question 4 came back with one empty side under the
    oversight-only reading and would have been labelled "the excluded arm was
    one side of this contrast" - which is false, and worse than saying nothing,
    because it invents an explanation a reader has no way to check.
    So the question's own manipulated axis must also BE the axis that was
    excluded.

    That axis is read off the id, which is written `<exposure>_vs_<outcome>` -
    the same parse report_charts.exposure_of does for its axis labels, reused
    rather than duplicated, and already pinned against the ids build_report
    emits by test_report_charts. A hand-kept list of which questions split on
    the oversight arms would be three entries today and stale the moment a
    thirteenth question is added.

    Returns the reason as a sentence, or "" when the question either still has
    both sides or lost one for a reason this exclusion did not cause.
    """
    if report_charts.exposure_of(section["id"]) != axis:
        return ""
    overall = section.get("overall") or {}
    a, b = overall.get("a") or {}, overall.get("b") or {}
    if a.get("n") and b.get("n"):
        return ""
    empty = "second" if a.get("n") else "first"
    return (f"not estimable with the arm excluded: the {empty} side of this "
            f"contrast is the arm that was dropped, so there is nothing left "
            f"to compare it against")


def build_report(output_dir: str, exclusion: str = NO_EXCLUSION) -> dict:
    summaries = load_summaries(output_dir)
    episodes = load_episodes(output_dir)
    # BEFORE anything reads either list. Both sources are narrowed by the same
    # predicate in one call - see exclude_arm - because questions 1-4 are
    # answered from the summaries and 5-12 from the episodes, and an exclusion
    # that reached only one of those would produce a report whose halves
    # describe different corpora while every number in it still rendered.
    summaries, episodes, arm_exclusion = exclude_arm(
        summaries, episodes, exclusion)
    # Arms rebuilt from episodes, carrying the text-only awareness numerator no
    # summary field holds. Questions 2 and 4 take the headline measure from the
    # summaries as before and this alongside it; see _text_reachable_block.
    arm_rows = awareness_arm_rows(episodes)
    # Arms rebuilt from episodes again, this time carrying each misaligned act
    # separately. Questions 1 and 3 report a UNION over the acts, and the acts do
    # not have the same support across the oversight arms - see
    # _common_support_block - so each of those two questions carries the per-act
    # contrast beside its composite.
    act_rows = act_arm_rows(episodes)
    questions = [
        question_oversight_vs_scheming(summaries, act_rows),
        question_oversight_vs_awareness(summaries, arm_rows),
        question_oversight_vs_misalignment(summaries, act_rows),
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

    # Marked on the section rather than worked out again by each consumer. The
    # console and the chart layer both have to know that a question lost its
    # comparison, and two independent derivations of "did this collapse" is the
    # shape this repository keeps being bitten by - so it is decided once, here,
    # where the exclusion that caused it is in scope.
    if arm_exclusion["axis"] is not None:
        for section in questions:
            if "contrasts" in section:
                continue
            reason = _collapsed_by_exclusion(section, arm_exclusion["axis"])
            if reason:
                section["collapsed_by_exclusion"] = reason

    return {
        "version": VERSION,
        "rollout_version": ROLLOUT_VERSION,
        # What corpus this document is about. Always present, including for the
        # unrestricted reading, so a consumer never has to distinguish "no
        # exclusion" from "an older report that predates exclusions" - the two
        # would otherwise both read as a missing key.
        "arm_exclusion": arm_exclusion,
        "output_dir": redact_paths(os.path.abspath(output_dir)),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_summary_files": len(summaries),
        "n_episode_files": len(episodes),
        "n_models": len(_models(summaries)),
        "data_quality": data_quality_facts(episodes, summaries),
        # Conduct rather than rates, and deliberately NOT in
        # `questions`: these are descriptive profiles, and the
        # question machinery would attach effect estimates to them.
        "characteristics": characteristics(episodes),
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
    parser.add_argument("--exclude-no-oversight", action="store_true",
                        help="answer every question again with the "
                             "no-oversight arm set aside, and write the "
                             "charts and JSON under separate names. A "
                             "sensitivity reading, not a correction: see "
                             "report/loading.py for what the arm's task "
                             "README promises and does not deliver")
    args = parser.parse_args()

    if not os.path.isdir(args.output_dir):
        parser.error(f"--output-dir {args.output_dir!r} does not exist")

    # Read off the flag once and passed down, never re-derived from `args`
    # further in. One Namespace is shared by reference across this run.
    exclusion = (EXCLUDE_NO_OVERSIGHT if args.exclude_no_oversight
                 else NO_EXCLUSION)
    report = build_report(args.output_dir, exclusion)
    if not report["n_summary_files"]:
        print(f"No summary files found in {redact_paths(args.output_dir)}.")
        return 1

    print(f"Analysing {redact_paths(args.output_dir)}: "
          f"{report['n_summary_files']} summary file(s), "
          f"{report['n_episode_files']} episode file(s), "
          f"{report['n_models']} model(s).")
    # Before the questions, not after: every rate below is on the narrowed
    # corpus, and a reader who meets that fact at the bottom has already read
    # the numbers as though it were the whole one.
    _print_arm_exclusion(report["arm_exclusion"])
    _print_data_quality(report["data_quality"])
    for section in report["questions"]:
        # "contrasts" is the paired-question shape; the others carry "overall".
        if "contrasts" in section:
            _print_variant_question(section)
        else:
            _print_question(section)

    # After the questions, because it answers a different kind of question and
    # reads as a footnote to them rather than as a thirteenth one.
    _print_characteristics(report["characteristics"])

    # Before the JSON is written, so `charts` lands in the file rather than
    # describing an artefact the report has no record of.
    if not args.no_charts:
        # A DIFFERENT DIRECTORY BY DEFAULT, and the reason is the whole point of
        # the flag: these charts hold different numbers under the same
        # filenames, and writing them over the pooled set would leave a
        # `charts/` whose contents cannot be told apart from the full-corpus
        # ones by looking at them. An explicit --chart-dir still wins, so a
        # caller who wants them somewhere else says so.
        chart_dir = args.chart_dir or os.path.join(
            args.output_dir, "charts" + _artefact_suffix(exclusion))
        written = report_charts.write_charts(report, chart_dir)
        if written:
            print(f"\n{len(written)} chart(s) written to "
                  f"{redact_paths(chart_dir)}:")
            for path in written:
                print(f"  {os.path.basename(path)}")
            report["charts"] = [redact_paths(p) for p in written]
        # Named, not merely absent. A reader comparing the two chart
        # directories will find files missing from this one, and "which ones
        # and why" is the first thing they need - otherwise a chart the
        # exclusion legitimately removed is indistinguishable from one that
        # failed to render.
        collapsed = [s["id"] for s in report["questions"]
                     if s.get("collapsed_by_exclusion")]
        if collapsed:
            print(f"\n{len(collapsed)} question(s) have no chart here: the "
                  f"excluded arm was one side of the contrast, so there is "
                  f"nothing left to compare against.")
            for question_id in collapsed:
                print(f"  {question_id}")
            report["charts_omitted_by_exclusion"] = collapsed

    # NOT run_report_*.json: that name sits inside load_episodes' own
    # `run_*.json` glob, so the default output would land in the namespace this
    # script scans and be re-read as a candidate episode on the next run. It is
    # skipped today only because a report has no "model" key - the same
    # bare-prefix collision find_run_files documents three prior instances of.
    json_out = args.json_out or os.path.join(
        args.output_dir,
        f"research_report{_artefact_suffix(exclusion)}"
        f"_{time.strftime('%Y%m%dT%H%M%S')}.json")
    os.makedirs(os.path.dirname(os.path.abspath(json_out)), exist_ok=True)
    with open(json_out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {redact_paths(json_out)}")
    return 0

# No `if __name__ == "__main__"` here. __main__.py is the entry point, and
# it says why: the package re-exports main(), so running THIS module with -m
# would execute it a second time and warn about it above every report.
