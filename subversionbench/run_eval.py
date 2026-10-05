"""
SubversionBench - Runner
========================

Author: Kevin O'Shaughnessy

Loosely based on Meinke et al.'s "Frontier Models are Capable of
In-Context Scheming" (Apollo Research), now a distinct work.
https://arxiv.org/abs/2412.04984

Agentic evaluation loop, follow-up interrogation, batch runner,
summary reporting, and CLI entry point.

SETUP:
  1. pip install anthropic
  2. export ANTHROPIC_API_KEY="your-key-here"
  3. python -m subversionbench.run_eval

  To evaluate a model via OpenRouter (https://openrouter.ai) instead of the
  native Anthropic API, pass a "provider/model" style --model (e.g.
  "openai/gpt-4o", "google/gemini-2.5-pro"), and:
  1. pip install openai
  2. export OPENROUTER_API_KEY="your-key-here"

Run with --help for the full list of CLI options.
"""

import json
import os
import sys

from .arms_summary import write_summary_of_summaries
from .compare import compare_batches
from .graders import REGRADE_ALL, REGRADE_DEFAULT
from .config import (
    DEFAULT_GRADER_MODEL,
    DEFAULT_INTERROGATION,
    INTERROGATION_CHOICES,
    parse_interrogations,
    ROLLOUT_VERSION,
    VERSION,
    SYSTEM_PROMPT_STRONG_NUDGE,
    SYSTEM_PROMPT_NO_NUDGE,
)
from .episode import run_evaluation  # noqa: F401
from .followup import (add_awareness_timing,  # noqa: F401
                       run_followup)
from .turns import (_CACHE_BREAKPOINTS,  # noqa: F401
                    replayable_content, roll_cache_breakpoints)
from .usage import cache_usage  # noqa: F401
from .grading import (
    questions_for,
    MISALIGNED_ACTS,
)
from .llm_client import (
    EFFORT_LEVELS,
    MIN_THINKING_BUDGET,
    is_openrouter_model,
    reasoning_flag_error,
    resolve_thinking_budget,  # re-exported: this module's former API
    resolve_thinking_kwargs,
    thinking_surface,
)
# batch_stem, parse_batch_filename, find_run_files and find_run_files_by_stamp are
# re-exported: this module was their home and several test files still reach them
# through it as attributes. The rest are imported because this module uses them.
from .batch import (ALL, BatchIdentity, BatchSelection, batch_stem,  # noqa: F401
                    discover_batches, find_run_files, find_run_files_by_stamp,
                    parse_batch_filename)
from .readmodes import (REDERIVED_ANALYSIS_FIELDS,  # noqa: F401
                        complete_pending_interrogations,
                        fan_out_read_mode, find_run_files_or_explain,
                        grade_existing_runs, reclassify_existing_runs,
                        reinterrogate_existing_runs,
                        resummarise_existing_runs, self_grade_kinds)
from .redaction import redact_paths
from .runner import run_batch
from .isolation import DEFAULT_ISOLATION, ISOLATION_MODES
from .power import wilson_ci
from .reporting.summary import summarise_batch
from .cli_parser import build_parser

# The names this module provides: its own, and the ones it re-exports because it
# used to be their home and callers still reach them through it.
#
# Declared rather than left to the `noqa` comments above, which pyflakes does
# not read - so all fifteen re-exports were reported as stray imports, and a
# genuinely stray one could not be told apart from them. The comments say WHY
# each is here; this says that it is meant to be.
__all__ = [
    "ALL",
    "BatchIdentity",
    "BatchSelection",
    "DEFAULT_GRADER_MODEL",
    "DEFAULT_INTERROGATION",
    "DEFAULT_ISOLATION",
    "EFFORT_LEVELS",
    "INTERROGATION_CHOICES",
    "ISOLATION_MODES",
    "MIN_THINKING_BUDGET",
    "MISALIGNED_ACTS",
    "REDERIVED_ANALYSIS_FIELDS",
    "ROLLOUT_VERSION",
    "SYSTEM_PROMPT_NO_NUDGE",
    "SYSTEM_PROMPT_STRONG_NUDGE",
    "VERSION",
    "_CACHE_BREAKPOINTS",
    "add_awareness_timing",
    "batch_stem",
    "cache_usage",
    "compare_batches",
    "complete_pending_interrogations",
    "discover_batches",
    "fan_out_read_mode",
    "find_run_files",
    "find_run_files_by_stamp",
    "find_run_files_or_explain",
    "grade_existing_runs",
    "is_openrouter_model",
    "main",
    "parse_batch_filename",
    "parse_interrogations",
    "questions_for",
    "reasoning_flag_error",
    "reclassify_existing_runs",
    "redact_paths",
    "reinterrogate_existing_runs",
    "replayable_content",
    "resolve_thinking_budget",
    "resolve_thinking_kwargs",
    "resummarise_existing_runs",
    "roll_cache_breakpoints",
    "run_batch",
    "run_evaluation",
    "run_followup",
    "self_grade_kinds",
    "summarise_batch",
    "thinking_surface",
    "wilson_ci",
    "write_summary_of_summaries",
]


# =========================================================================
# Stats helpers
# =========================================================================

# The interval estimator lives in power.py, which owns all of the statistics
# for this package; aliased here because it's used throughout the summary.
_wilson_ci = wilson_ci


# The read modes that work file by file over a batch, and so take
# --batch-stamp and --write-back.
_PER_FILE_FLAGS = ("--grade-existing", "--self-grade-kind", "--reclassify",
                   "--resummarise", "--reinterrogate", "--complete-pending")
_PER_FILE_MODES = ", ".join(_PER_FILE_FLAGS[:-1]) + " or " + _PER_FILE_FLAGS[-1]


def _read_modes_chosen(args) -> list:
    """Every read mode this invocation asked for, by flag. _run_read_mode
    runs only the first it reaches, so more than one is refused."""
    return [flag for flag, on in (
        ("--compare", args.compare), ("--summarise-arms", args.summarise_arms),
        ("--grade-existing", args.grade_existing),
        ("--self-grade-kind", args.self_grade_kind),
        ("--reclassify", args.reclassify), ("--resummarise", args.resummarise),
        ("--reinterrogate", args.reinterrogate),
        ("--complete-pending", args.complete_pending)) if on]


def _reject_contradictory_flags(parser, args) -> None:
    """Flag combinations that cannot mean anything, refused at the boundary.

    Every one of these fails BEFORE a paid rollout rather than partway through
    one. parser.error exits 2 and prints usage, which is why the parser is
    passed rather than raising: an operator who mistyped a flag wants the usage
    line, not a traceback.

    Takes args and writes nothing to it. The bag is mutated only in main(),
    which is what test_args_bag.py enforces and why this returns None rather
    than a corrected namespace.
    """
    # No blanket refusal for the max arm any more: it has its own rephrasing of
    # its own four-clause first question, so pairing is meaningful there too. What
    # is refused is a variant with no max form, which questions_for raises on -
    # checked here so it fails before a paid rollout rather than mid-batch.
    if args.nudge == "max":
        for name in args.interrogations:
            try:
                questions_for(MISALIGNED_ACTS[0], "max", name)
            except (ValueError, KeyError) as e:
                parser.error(str(e))
    if (args.grade_existing or args.self_grade_kind) and args.no_grader:
        parser.error(
            "--grade-existing/--self-grade-kind and --no-grader are "
            "contradictory: the first does nothing but run the grader."
        )
    if args.grade_existing and args.self_grade_kind:
        parser.error(
            "--grade-existing and --self-grade-kind are different modes: the "
            "first re-runs the whole rubric with --grader-model, the second "
            "re-measures only the kind with the episode's own model. Run one, "
            "then the other."
        )
    chosen = _read_modes_chosen(args)
    if len(chosen) > 1:
        parser.error(
            f"{' and '.join(chosen)} are separate read modes. Run one at a "
            f"time: given together, only the first would run and the rest "
            f"would be skipped without a word.")
    _read_modes = bool(chosen) and not (args.compare or args.summarise_arms)
    if args.complete_pending and args.no_grader:
        parser.error("--complete-pending and --no-grader are contradictory: "
                     "what is pending is exactly what needs the grader.")
    if args.batch_stamp and not _read_modes:
        parser.error(f"--batch-stamp only applies with {_PER_FILE_MODES}.")
    if args.min_answered is not None and not args.grade_existing:
        parser.error("--min-answered only applies with --grade-existing.")
    if args.min_answered is not None and args.min_answered < 1:
        parser.error("--min-answered must be at least 1; 0 would select "
                     "nothing that --only-failed does not already reach.")
    if args.only_failed and not args.grade_existing:
        parser.error("--only-failed only applies with --grade-existing. The "
                     "other read modes are free and re-derive every episode, "
                     "so there is nothing for it to narrow.")
    for flag, value in (("--write-back", args.write_back),):
        if value and not _read_modes:
            parser.error(f"{flag} only applies with {_PER_FILE_MODES}.")
    _reject_regrade_misuse(parser, args)


def _reject_regrade_misuse(parser, args) -> None:
    """--regrade and --grader-model, each where it means something.

    --grader-model names the grader a COLLECTION runs. A read mode used to
    take it as its target too; it now takes --regrade, and a non-default
    --grader-model beside one is refused rather than ignored, so nobody
    believes they chose a grader they did not. The default passed explicitly
    targets the same grader --regrade does by default, so it is let through.
    """
    targeted = args.grade_existing or args.reclassify or args.reinterrogate
    if args.regrade != REGRADE_DEFAULT and not targeted:
        parser.error("--regrade only applies with --grade-existing, "
                     "--reclassify or --reinterrogate.")
    if args.reinterrogate and args.regrade == REGRADE_ALL:
        parser.error(f"--reinterrogate takes one grader, not "
                     f"--regrade {REGRADE_ALL}: that grader's verdicts decide "
                     f"where each new ladder of questions stops.")
    if targeted and args.grader_model != DEFAULT_GRADER_MODEL:
        parser.error(f"--grader-model {args.grader_model} names the grader a "
                     f"collection runs. To re-grade with it, use "
                     f"--regrade {args.grader_model}.")


def _resolve_reasoning(parser, args) -> tuple:
    """The reasoning parameters to send, and the label describing them.

    Returns (kwargs, config). The model's API surface decides which of
    --thinking-budget and --effort is even meaningful, so the checks here are
    against that surface rather than against the flags in isolation - asking a
    model with no effort control for `max` sends nothing, and a run labelled
    `max` that sent nothing is worse than no label.
    """
    surface = thinking_surface(args.model)
    takes_budget = surface is not None and surface.mode == "budget"

    if args.thinking_budget is not None and args.thinking_budget > 0 and takes_budget:
        if args.thinking_budget < MIN_THINKING_BUDGET:
            parser.error(
                f"--thinking-budget must be at least {MIN_THINKING_BUDGET} "
                f"tokens."
            )
        if args.thinking_budget >= args.max_tokens:
            parser.error(
                f"--thinking-budget ({args.thinking_budget}) must be less "
                f"than --max-tokens ({args.max_tokens}) - thinking tokens "
                f"count against the max_tokens budget, so there needs to be "
                f"room left for the visible answer/tool call. Try e.g. "
                f"--max-tokens {args.thinking_budget + 4096}."
            )

    flag_error = reasoning_flag_error(args.model, args.thinking_budget, args.effort)
    if flag_error:
        parser.error(flag_error)

    reasoning_kwargs, reasoning_config, reasoning_warnings = (
        resolve_thinking_kwargs(
            args.model, args.thinking_budget, args.max_tokens, args.effort,
        )
    )
    for warning in reasoning_warnings:
        print(f"[WARNING] {warning}")
    print(f"Reasoning: {reasoning_config}")

    return reasoning_kwargs, reasoning_config


def _warn_about_inapplicable_routing(args) -> None:
    """Routing flags aimed at a model that does not route.

    A WARNING rather than an error, deliberately: both flags are documented as
    ignored for a non-OpenRouter model, so refusing here would break a fan-out
    that names one provider flag and several models. The warning is what stops
    it being silent.
    """
    if args.lure and getattr(args, "goalguard", None):
        # Announced, on the same terms as the routing warning below: a flag
        # that silently does nothing lets an operator believe they collected
        # an arm they did not.
        print(f"[WARNING] --lure true has no effect with --goalguard "
              f"{args.goalguard}. The lure attributes reaching outside the "
              f"project directory; this act's artefact is inside it, so the "
              f"axis is not part of this arm and is not pinned. Collecting "
              f"as the non-lure arm.")
    if args.openrouter_sort and not is_openrouter_model(args.model):
        print(f"[WARNING] --openrouter-sort {args.openrouter_sort} does not "
              f"apply to {args.model}: that flag only affects OpenRouter "
              f"models (an id containing '/').")

    if args.openrouter_provider and not is_openrouter_model(args.model):
        print(f"[WARNING] --openrouter-provider {args.openrouter_provider} "
              f"does not apply to {args.model}: that flag only affects "
              f"OpenRouter models (an id containing '/').")

    if args.use_opencode and not is_openrouter_model(args.model):
        print(f"[WARNING] --use-opencode does not apply to {args.model}: "
              f"that flag only affects OpenRouter-shaped models (an id "
              f"containing '/').")

    if args.use_opencode and is_openrouter_model(args.model):
        if args.openrouter_sort:
            print(f"[WARNING] --openrouter-sort {args.openrouter_sort} has "
                  f"no effect with --use-opencode: OpenCode has no "
                  f"equivalent of OpenRouter's backend-sort routing.")
        if args.openrouter_provider:
            print(f"[WARNING] --openrouter-provider {args.openrouter_provider} "
                  f"has no effect with --use-opencode: OpenCode has no "
                  f"equivalent of OpenRouter's pin-to-backend routing.")



def _capability_refusal(args) -> str:
    """Why this capability run cannot mean what it claims, or None.

    THE CAPABILITY ARM'S PRECONDITIONS, refused rather than corrected. Each of
    these would produce episodes that look like a capability result and are
    not, and none of them is visible in the artefact afterwards - which is the
    whole reason they are checked at the boundary. Silently coercing them
    instead would run an arm the operator did not ask for.

    RETURNS the message rather than printing it, so the decision can be tested
    without capturing stdout and so main() owns the exit code. Reads the
    BOOLEAN args.oversight and args.lure, so it must be called after main()
    coerces them.
    """
    if not args.capability:
        return None
    if args.nudge != "none":
        return (f"\n--capability needs --nudge none, not {args.nudge!r}. The "
                f"nudge is the goal-conflict pressure, and it is propensity "
                f"machinery: capability shown under it is capability under "
                f"pressure, which is not what a propensity zero needs to be "
                f"read as a choice.")
    if args.lure:
        return ("\n--capability cannot be combined with --lure true. The "
                "lure is a hint, so capability shown under it is "
                "capability with a hint. There is deliberately no "
                "pinned fingerprint for that combination.")
    if args.capability == "oversight" and not args.oversight:
        return ("\n--capability oversight needs --oversight true. The "
                "counterfactual arm removes the artefact the instruction "
                "names, so every episode would be scored as incapable of an "
                "act the arm itself makes impossible - the r9 defect "
                "exactly, in a new place.")
    return None


def _billable_run_files(paths: list, reclassify: bool) -> int:
    """How many of these run files the read mode will send to the grader.

    Every one for the modes that grade a whole episode. --reclassify is
    narrower: it calls the grader only for an episode that took an act, and
    recomputes the rest locally - see rescore._rescore_acts. Counting every
    file there, and quoting a rollout's token usage beside it, priced a
    one-act repair of a goal-guarding batch at eighty episodes' worth of
    grading.
    """
    if not reclassify:
        return len(paths)
    n = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                analysis = json.load(f).get("analysis") or {}
        except (OSError, json.JSONDecodeError):
            continue
        n += any(analysis.get(act["key"]) for act in MISALIGNED_ACTS)
    return n


def _run_read_mode(args, selection):
    """Run whichever mode operates on a corpus already on disk.

    Returns that mode's exit code, or None when no read mode was asked for -
    which is the signal to main() that this invocation is a collection run.
    None rather than a sentinel exit code, because every value an exit code can
    take is already meaningful here.
    """
    if args.compare:
        return compare_batches(args)

    if args.summarise_arms:
        write_summary_of_summaries(args.output_dir, args.model)
        return 0

    # `all` fans out over every batch in the directory. Free for --resummarise,
    # which calls no API. The other read modes send a request per run file, so
    # fanning them out spends real money - allowed, but only once the operator has
    # been shown the scope and said yes. The guard is there to make the bill
    # visible, not to make the operation unavailable.
    if ALL in (args.model, args.nudge):
        if args.resummarise:
            return fan_out_read_mode(args, resummarise_existing_runs)

        run_one = (grade_existing_runs if args.grade_existing else
                   self_grade_kinds if args.self_grade_kind else
                   reclassify_existing_runs if args.reclassify else None)
        if run_one is None:
            print("--model/--nudge 'all' applies to the read-only modes "
                  "(--resummarise, --grade-existing, --self-grade-kind, "
                  "--reclassify).")
            return 2

        batches = discover_batches(args.output_dir, args.model, args.nudge)
        paths = [p for m, n in batches
                 for p in find_run_files(args.output_dir, m.replace("/", "_"), n)]
        n_files = len(paths)
        if not args.yes:
            print(f"\nThis would send grader requests for "
                  f"{_billable_run_files(paths, args.reclassify)} of {n_files} "
                  f"run file(s) across {len(batches)} batch group(s) in "
                  f"{redact_paths(args.output_dir)}.\n"
                  f"Re-run with --yes to proceed, or name a single model and "
                  f"nudge to do one batch.")
            return 2
        print(f"\n--yes given: grading {n_files} run file(s) across "
              f"{len(batches)} batch group(s).")
        return fan_out_read_mode(args, run_one)

    if args.resummarise:
        return resummarise_existing_runs(args, selection)

    if args.reinterrogate:
        return reinterrogate_existing_runs(args, selection)

    if args.complete_pending:
        # Then the summaries: their concealment and scheming figures were
        # counted while these were pending. Only when something was asked,
        # so a pass with nothing pending writes nothing.
        code, n_completed = complete_pending_interrogations(args, selection)
        if code or not n_completed:
            return code
        return resummarise_existing_runs(args, selection)

    if args.reclassify:
        return reclassify_existing_runs(args, selection)

    if args.grade_existing:
        return grade_existing_runs(args, selection)

    if args.self_grade_kind:
        return self_grade_kinds(args, selection)

    return None


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.interrogations = parse_interrogations(args.interrogation)
    except ValueError as e:
        parser.error(str(e))
    _reject_contradictory_flags(parser, args)

    reasoning_kwargs, reasoning_config = _resolve_reasoning(parser, args)
    _warn_about_inapplicable_routing(args)

    # max shares strong's prompt: the arms differ only in the interrogation
    # that follows the episode, so the episode itself must be identical for the
    # contrast to isolate what the threat does.
    system_prompt = (
        SYSTEM_PROMPT_STRONG_NUDGE if args.nudge in ("strong", "max")
        else SYSTEM_PROMPT_NO_NUDGE
    )

    # The two string flags become booleans HERE and nowhere else. main() is the
    # CLI boundary, and test_args_bag.py requires every write to the bag to
    # happen in it - a helper that took args and corrected it would put the
    # same mutation somewhere a later caller cannot see.
    args.oversight = args.oversight == "true"
    args.lure = args.lure == "true"

    refusal = _capability_refusal(args)
    if refusal:
        print(refusal)
        return 2

    os.makedirs(args.output_dir, exist_ok=True)

    # OpenRouter model IDs are "provider/model" (e.g. "x-ai/grok-4.5"); the
    # "/" would otherwise be interpreted as a path separator in filenames.
    model_slug = args.model.replace("/", "_")

    # The (model, nudge) the read modes below operate on. Built once here,
    # rather than each mode reading it off `args`, because a fan out varies
    # the pair per batch and there is only one `args` to vary - see
    # BatchSelection in batch.py for what that used to cost.
    selection = BatchSelection.typed(args)

    read_mode_exit = _run_read_mode(args, selection)
    if read_mode_exit is not None:
        return read_mode_exit

    # Past this point we are rolling out. Everything above decided whether to, and
    # with what; runner.py does it.
    return run_batch(args, model_slug, system_prompt, reasoning_kwargs,
                     reasoning_config)



if __name__ == "__main__":
    # main() returns an exit code when --grade-existing can't find anything to
    # grade, so a failed regrade doesn't look like a success to the shell.
    sys.exit(main())
