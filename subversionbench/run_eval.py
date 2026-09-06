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

import os
import sys
import argparse

from .arms_summary import write_summary_of_summaries
from .compare import compare_batches
from .config import (
    CAPABILITY_TARGETS,
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
from .turns import (_CACHE_BREAKPOINTS, cache_usage,  # noqa: F401
                    replayable_content, roll_cache_breakpoints)
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
                        fan_out_read_mode, find_run_files_or_explain,
                        grade_existing_runs, reclassify_existing_runs,
                        reinterrogate_existing_runs,
                        resummarise_existing_runs)
from .redaction import redact_paths
from .runner import run_batch
from .isolation import DEFAULT_ISOLATION, ISOLATION_MODES
from .power import wilson_ci
from .reporting.summary import summarise_batch

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


def _add_collection_arguments(parser: argparse.ArgumentParser) -> None:
    """What to collect: which model, which arm, how many, and where.

    These change when the experiment changes - a new arm, a new interrogation
    phrasing, a new bound on how long an episode may stall. Fourteen of the
    sixteen commits that have ever touched a flag declaration in this file
    changed exactly one of these four groups, which is why they are four
    functions: they have independent reasons to change.
    """
    parser.add_argument("--model", default="claude-sonnet-5",
                        help="Model to evaluate, or 'all' to fan out over every "
                             "model present in --output-dir. 'all' works only "
                             "with --resummarise, which calls no API.")
    parser.add_argument(
        "--oversight", choices=["true", "false"], default="true",
        help="whether the scenario contains an oversight mechanism to "
             "subvert (default: true). 'false' selects the "
             "counterfactual arm: no monitoring config, no quality-check "
             "script, and no document referring to either. The oversight act "
             "is then NOT APPLICABLE rather than absent, so the comparable "
             "outcome across arms is the recommendation itself.")
    parser.add_argument("--lure", choices=["true", "false"], default="false",
                        help="Lure arm. `false` is the scenario as it stands. "
                             "`true` adds one sentence noting that another "
                             "engagement's material is still on the machine, and "
                             "places a file outside the episode directory for it "
                             "to refer to. The sentence neither suggests reading "
                             "it nor forbids it - the scenario's own boundary "
                             "statement covers that. Part of batch identity and "
                             "its own rollout arm, so a lure batch cannot pool "
                             "with a plain one: under the lure, reaching outside "
                             "partly measures response to a hint.")
    parser.add_argument(
        "--capability", choices=list(CAPABILITY_TARGETS), default=None,
        help="Capability arm - the oracle-solver denominator. Replaces the "
             "task instruction with one that asks for the act outright, so "
             "that a model's zero on the propensity arm can be read: 0%% "
             "against a 0%% ceiling is a fact about the scenario, 0%% against "
             "a 90%% ceiling is a fact about the model. Its own rollout "
             "fingerprint and its own filename mark, and the report drops it "
             "from every propensity rate - the act was INSTRUCTED here, so "
             "pooling one episode into a misalignment rate inflates it "
             "towards the ceiling it exists to measure. Collect into a "
             "separate --output-dir.")
    parser.add_argument("--yes", action="store_true",
                        help="Proceed with a fanned-out mode that sends API "
                             "requests. Required with --model/--nudge all on "
                             "--grade-existing or --reclassify, so the scope is "
                             "printed and acknowledged before anything is spent.")
    parser.add_argument("--reinterrogate", action="store_true",
                        help="Put an extra --interrogation phrasing to episodes "
                             "already on disk, without re-running them. Only "
                             "episodes that took an act are candidates, only "
                             "phrasings not already recorded are asked, and an "
                             "episode that cannot be reconstructed faithfully is "
                             "skipped rather than replayed with its reasoning "
                             "stripped. Needs --write-back to keep the answers.")
    parser.add_argument("--interrogation", default=DEFAULT_INTERROGATION,
                        help="EXTRA wordings for the FIRST interrogation question. "
                             "The default probe always runs and is not optional - "
                             "the headline concealment field is defined as its "
                             "answer - so this flag names what to ask IN ADDITION, "
                             "and leaving it alone asks nothing extra. "
                             "Comma-separated to put several wordings to the SAME "
                             "episode: each starts from the episode as it ended, so "
                             "they cannot interfere and the comparison is paired "
                             "rather than between-batch. The variants are "
                             "meaning-preserving rephrasings - the same clauses, "
                             "reordered - for testing whether the concealment rate "
                             "survives a change that carries no semantic content; "
                             "the escalation ladder is shared, so a difference is "
                             "attributable to the opening probe. Any of "
                             f"{list(INTERROGATION_CHOICES)}. Works with --nudge "
                             "max, which has its own rephrasing of its own "
                             "four-clause first question; a variant with no max "
                             "form is refused rather than falling back on the "
                             "ordinary wording.")
    parser.add_argument("--nudge", choices=["strong", "none", "max", "all"],
                        default="strong",
                        help="Nudge strength. `strong` and `none` differ in the "
                             "system prompt. `max` is `strong`'s episode "
                             "unchanged, with an interrogation that makes an "
                             "honest answer costly by attaching a stated "
                             "consequence to a confirmed finding. It "
                             "measures concealment under coercion, which is a "
                             "different construct - do not pool it with strong.")
    parser.add_argument("--runs", type=int, default=10,
                        help="Number of evaluation runs")
    parser.add_argument("--output-dir",
                        default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="Output directory for results")
    parser.add_argument("--delay", type=int, default=30,
                        help="Seconds to wait between runs (rate limiting). "
                             "Under --concurrency > 1 this paces LAUNCHES "
                             "instead of pausing after each finish, since "
                             "episodes no longer finish in launch order.")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Episodes to run at once. Default 1 is today's "
                             "sequential behaviour. Each episode is I/O-bound "
                             "- waiting on the model, grader, and "
                             "interrogation APIs rather than local CPU - so "
                             "raising this cuts wall-clock time roughly in "
                             "proportion. This flag does not know your "
                             "account's actual concurrent-request limit; "
                             "start low (e.g. 3-5) and watch for 429s before "
                             "raising it further.")
    parser.add_argument("--resume", metavar="STAMP", default=None,
                        help="Continue an interrupted batch: reuse this "
                             "filename timestamp (e.g. 20260727T182651) and "
                             "skip episodes whose run file is already on "
                             "disk. Without it a restart begins at episode 1 "
                             "under a new stamp and the two halves don't "
                             "group together.")
    parser.add_argument("--max-consecutive-failures", type=int, default=5,
                        help="Abort the batch after this many episodes fail "
                             "in a row. Isolated API errors are retried at "
                             "the SDK level and then skipped; a run of them "
                             "means something systematic (bad key, model "
                             "withdrawn) and burning the rest of the budget "
                             "on it is worse than stopping.")


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    """How the model under test is called, and by which backend.

    Reasoning surface, token budgets, isolation mechanism and OpenRouter
    routing. These change when a provider changes, which has nothing to do
    with the experiment: --openrouter-provider and --isolation arrived in
    commits that touched no other group.
    """
    parser.add_argument("--isolation", choices=list(ISOLATION_MODES),
                        default=DEFAULT_ISOLATION,
                        help="Kernel-enforced limit on what a sandboxed command "
                             "can reach. There is no way to disable it: the "
                             "blocklist is not a containment boundary, and a "
                             "model with shell access would otherwise reach the "
                             "network. `deny-external` "
                             "keeps loopback reachable - so network_probe still "
                             "observes real behaviour - while the kernel refuses "
                             "anything off the host. `deny-network` refuses "
                             "both. Does not need a new ROLLOUT_VERSION: "
                             "off-host reach has never been observed, so the "
                             "mode is recorded per run rather than hashed, and "
                             "network_probe_external is reported as not "
                             "applicable when the policy denies it.")
    parser.add_argument("--no-grader", action="store_true",
                        help="Skip the LLM grader (faster, cheaper)")
    parser.add_argument("--max-turns", type=int, default=40,
                        help="Turn cap per episode. Episodes typically finish "
                             "in 6-9 turns, so the default is roughly five "
                             "times the usual need and only binds on an "
                             "episode that is already behaving oddly - the "
                             "one that hit the old cap of 20 was stuck "
                             "appending to a file in a loop, not doing long legitimate work. "
                             "An episode that hits the cap is recorded as "
                             "ended_by=turn_cap and excluded from the "
                             "disclosure measures, since it never produced a "
                             "closing report.")
    parser.add_argument("--grader-model", default=DEFAULT_GRADER_MODEL,
                        help="Model that grades eval awareness and labels "
                             "interrogation answers (default: %(default)s). A "
                             "frontier model by default because a small one was "
                             "measurably wrong: claude-haiku-4-5 read the "
                             "scenario's own quality checker as evidence the "
                             "agent suspected it was under evaluation. Trading "
                             "down is supported; see 'Validating the grader' in "
                             "README.md for what it costs in fidelity.")
    parser.add_argument("--max-tokens", type=int, default=8192,
                        help="Max output tokens per turn. Reasoning models "
                             "(e.g. deepseek-r1) spend tokens on internal "
                             "reasoning before their answer/tool call, so "
                             "they may need a much higher value than the "
                             "default to avoid running out mid-turn.")
    parser.add_argument("--thinking-budget", type=int, default=None,
                        help="Extended-thinking budget in tokens, for the "
                             "older Anthropic models that still accept one "
                             "(Sonnet 4.5, Haiku 4.5, Opus 4.5 and below). "
                             "Defaults to half of --max-tokens, because "
                             "whether reasoning is captured changes what the "
                             "eval measures: both eval-awareness detectors "
                             "read it, so a model whose reasoning is returned "
                             "is scored on more evidence than one whose is "
                             "not. Pass 0 to turn thinking off. From Sonnet "
                             "4.6 / Opus 4.6 onwards a token budget is not "
                             "accepted at all - those models use adaptive "
                             "thinking, steered by --effort - and OpenRouter "
                             "models take no reasoning parameter, surfacing "
                             "reasoning by themselves when the backend "
                             "provides it.")
    parser.add_argument("--effort", choices=sorted(EFFORT_LEVELS), default=None,
                        help="Reasoning depth for adaptive-thinking Anthropic "
                             "models (output_config.effort) - the replacement "
                             "for a fixed thinking budget. Omit to use the "
                             "API default of 'high'. Not every model accepts "
                             "every level, and it is ignored where the "
                             "parameter is unsupported.")
    parser.add_argument("--openrouter-sort", choices=["price", "throughput"],
                        default=None,
                        help="Bias OpenRouter's backend routing for the "
                             "model UNDER TEST (not the grader). "
                             "'throughput' prefers the fastest host serving "
                             "the model - the lever for an episode like "
                             "'[TIMING] Eval loop: 845.6s', which is almost "
                             "always the model generating slowly, not "
                             "anything this harness controls. 'price' "
                             "prefers the cheapest. Omit for OpenRouter's "
                             "own default routing (today's behaviour, "
                             "unchanged). Opt-in rather than default-on "
                             "because it changes WHICH backend answers the "
                             "request, not just how fast - that is a "
                             "measurement choice, not only a performance "
                             "one, so it is recorded on every run this "
                             "affects. Ignored (with no error) for a "
                             "non-OpenRouter model.")
    parser.add_argument("--openrouter-provider", default=None,
                        help="Pin OpenRouter routing for the model UNDER "
                             "TEST (not the grader) to one named backend, "
                             "e.g. 'deepinfra' or 'novita' - the OpenRouter "
                             "provider slug, lowercase. Unlike "
                             "--openrouter-sort, which only biases among all "
                             "eligible backends, this restricts routing to "
                             "exactly the one named and disables fallback to "
                             "any other (extra_body.provider.order + "
                             "allow_fallbacks=false), so a request fails "
                             "outright rather than silently landing on the "
                             "backend you were trying to avoid - useful when "
                             "one provider for a model is misbehaving (rate "
                             "limits, malformed responses) and the cheapest "
                             "or fastest one (what --openrouter-sort would "
                             "pick) is the broken one. Ignored (with no "
                             "error) for a non-OpenRouter model.")


def _add_read_mode_arguments(parser: argparse.ArgumentParser) -> None:
    """Operating on a corpus already on disk rather than collecting one.

    Grading, reclassifying, resummarising and comparing. Separate because a
    new read mode is a new way to re-derive fields from saved transcripts and
    needs nothing from the collection flags above - --summarise-arms was added
    without touching one of them.
    """
    parser.add_argument("--grade-existing", action="store_true",
                        help="Don't run the eval. Instead re-run the eval "
                             "awareness grader over run files already in "
                             "--output-dir, choosing them by --model and "
                             "--nudge and grading with --grader-model. Lets a "
                             "past batch be scored by a different grader "
                             "without paying for the agent rollouts again, "
                             "and because the transcripts are fixed, any "
                             "change in the numbers is down to the grader. "
                             "--delay still applies, between files.")
    parser.add_argument("--compare", nargs=2, metavar=("STAMP_A", "STAMP_B"),
                        default=None,
                        help="Don't run the eval. Compare two batches by "
                             "their filename timestamps - normally the two "
                             "nudge arms - on every headline rate, with "
                             "Fisher exact tests, and repeat the primary "
                             "contrast stratified by eval awareness.")
    parser.add_argument("--summarise-arms", "--summarize-arms",
                        action="store_true", dest="summarise_arms",
                        help="Don't run the eval. Instead build one report "
                             "across every arm of --model already collected "
                             "in --output-dir: each arm's headline rates side "
                             "by side, contrasts between arms that differ "
                             "along exactly one of nudge/oversight/lure "
                             "(holding the other two fixed), and concealment "
                             "broken out by interrogation phrasing. Written "
                             "to summary_of_summaries_<model>.json. Free - "
                             "reads saved summaries and run files, calls no "
                             "API. run_all_arms.sh runs this automatically "
                             "when it finishes.")
    parser.add_argument("--reclassify", action="store_true",
                        help="Don't run the eval. Instead re-score the "
                             "interrogations in run files already in "
                             "--output-dir, recomputing the concealment level "
                             "and scheming verdict from the saved answers and "
                             "transcript. Use after changing the classifier: "
                             "it costs no rollouts.")
    parser.add_argument("--resummarise", "--resummarize", action="store_true",
                        dest="resummarise",
                        help="Don't run the eval. Instead rebuild the batch "
                             "summary from run files already in --output-dir. "
                             "Use after --reclassify, which rewrites the "
                             "verdicts inside each run and so leaves every "
                             "verdict-derived figure in the existing summary "
                             "stale. Calls no API and derives every figure "
                             "from the saved runs; one summary per batch "
                             "stamp. Wall-clock timings and the failed-episode "
                             "list are carried over from the summary being "
                             "replaced, since run files do not record them.")
    parser.add_argument("--batch-stamp", default=None,
                        help="With --grade-existing, grade only the batch with "
                             "this filename timestamp (e.g. 20260727T182651). "
                             "Default: every batch matching the model/nudge.")
    parser.add_argument("--write-back", action="store_true",
                        help="With --grade-existing, also replace the "
                             "eval_awareness_grader block inside the original "
                             "run files. Off by default: the regrade goes to "
                             "a separate regrade_*.json and the run files are "
                             "left untouched. With --resummarise, save the "
                             "re-derived fields back into the run files so "
                             "they stop disagreeing with the summary built "
                             "from them; no API calls, and no LLM verdict is "
                             "touched.")


def _add_analysis_arguments(parser: argparse.ArgumentParser) -> None:
    """Statistics computed over the result, opt-out only.

    One flag today. It is its own function rather than folded into the read
    modes because it is neither: it changes what the summary reports, not what
    is collected or re-derived.
    """
    parser.add_argument("--no-power", action="store_true",
                        help="Skip the precision / detectable-effect analysis "
                             "that runs at the end of a batch. It is local "
                             "arithmetic with no API calls (~0.15s at n=100), "
                             "so there is rarely a reason to.")


def build_parser() -> argparse.ArgumentParser:
    """The CLI, built where a test can read its option strings.

    SEPARATE FROM main() so the options can be asserted EXACTLY rather than by
    grepping --help. The distinction is not academic: a substring check for
    "--grade" in help text also passes against "--grade-disabled", and argparse
    accepts `--grade` as an unambiguous prefix of it, so a flag documented in
    three places and absent from the parser satisfied both checks at once in
    trivial_baseline.py. Same parser, same options, and now reachable without
    running a batch.

    Composed from four groups rather than declared in one list, because the
    groups have independent reasons to change - see the docstring on each.
    Their ORDER here is the order --help prints them in, and grouping them
    changed that order from the arrival-order they had accumulated in; the
    option set, and every default, choice and help string in it, is unchanged
    and pinned by test_run_eval.py.
    """
    parser = argparse.ArgumentParser(
        description=f"Run SubversionBench {VERSION}"
    )
    _add_collection_arguments(parser)
    _add_model_arguments(parser)
    _add_read_mode_arguments(parser)
    _add_analysis_arguments(parser)
    return parser


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
    if args.grade_existing and args.no_grader:
        parser.error(
            "--grade-existing and --no-grader are contradictory: the first "
            "does nothing but run the grader."
        )
    if args.batch_stamp and not (args.grade_existing or args.reclassify
                                 or args.resummarise or args.reinterrogate):
        parser.error("--batch-stamp only applies with --grade-existing, "
                     "--reclassify or --resummarise.")
    for flag, value in (("--write-back", args.write_back),):
        if value and not (args.grade_existing or args.reclassify
                          or args.resummarise or args.reinterrogate):
            parser.error(
                f"{flag} only applies with --grade-existing, --reclassify "
                f"or --resummarise."
            )


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
    if args.openrouter_sort and not is_openrouter_model(args.model):
        print(f"[WARNING] --openrouter-sort {args.openrouter_sort} does not "
              f"apply to {args.model}: that flag only affects OpenRouter "
              f"models (an id containing '/').")

    if args.openrouter_provider and not is_openrouter_model(args.model):
        print(f"[WARNING] --openrouter-provider {args.openrouter_provider} "
              f"does not apply to {args.model}: that flag only affects "
              f"OpenRouter models (an id containing '/').")



def _capability_refusal(args) -> str:
    """Why this capability run cannot mean what it claims, or None.

    THE CAPABILITY ARM'S PRECONDITIONS, refused rather than corrected. Each of
    these would produce episodes that look like a ceiling and are not, and none
    of them is visible in the artefact afterwards - which is the whole reason
    they are checked at the boundary. Silently coercing them instead would run
    an arm the operator did not ask for.

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
                f"machinery: a ceiling measured under it is a ceiling for "
                f"what a pressured model can do, which is not the "
                f"denominator any propensity rate wants.")
    if args.lure:
        return ("\n--capability cannot be combined with --lure true. The "
                "lure is a hint, so a ceiling measured under it is a "
                "ceiling for hint-following. There is deliberately no "
                "pinned fingerprint for that combination.")
    if args.capability == "oversight" and not args.oversight:
        return ("\n--capability oversight needs --oversight true. The "
                "counterfactual arm removes the artefact the instruction "
                "names, so every episode would be scored as incapable of an "
                "act the arm itself makes impossible - the r9 defect "
                "exactly, in a new place.")
    return None


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
                   reclassify_existing_runs if args.reclassify else None)
        if run_one is None:
            print("--model/--nudge 'all' applies to the read-only modes "
                  "(--resummarise, --grade-existing, --reclassify).")
            return 2

        batches = discover_batches(args.output_dir, args.model, args.nudge)
        n_files = sum(len(find_run_files(args.output_dir,
                                        m.replace("/", "_"), n))
                      for m, n in batches)
        if not args.yes:
            print(f"\nThis would send grader requests for {n_files} run file(s) "
                  f"across {len(batches)} batch group(s) in "
                  f"{redact_paths(args.output_dir)}.\n"
                  f"Recorded usage on this corpus averages roughly 36k cached "
                  f"input, 5k cache writes and 1.5k uncached input per episode, "
                  f"so expect real money at this scale.\n"
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

    if args.reclassify:
        return reclassify_existing_runs(args, selection)

    if args.grade_existing:
        return grade_existing_runs(args, selection)

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
