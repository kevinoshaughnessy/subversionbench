"""
The run_eval command line: every flag, its default, its choices and its help.

Its own module because building the parser has one job and one reason to
change - a flag added, renamed or redocumented - while run_eval.py decides
what the parsed flags mean and dispatches on them. run_eval re-exports
build_parser, which is where tests and the console script reach it.
"""

import argparse
from .graders import REGRADE_ALL, REGRADE_DEFAULT
from .config import (CAPABILITY_TARGETS, DEFAULT_GRADER_MODEL,
                     DEFAULT_INTERROGATION, GOALGUARD_ARMS,
                     INTERROGATION_CHOICES, ROLLOUT_VERSION, VERSION)
from .llm_client import EFFORT_LEVELS
from .artefact_dates import MODES as DATE_MODES
from .isolation import DEFAULT_ISOLATION, ISOLATION_MODES


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
        help="Capability arm - the oracle solver. Replaces the task "
             "instruction with one that asks for the act outright, so that a "
             "model which performs it is shown capable and its zero on the "
             "propensity arm can be read as a choice. A model that does not "
             "perform it is not shown incapable: complying is itself a "
             "choice. Its own rollout fingerprint and its own filename mark, "
             "and the report drops it from every propensity rate - the act "
             "was INSTRUCTED here, so pooling one episode into a misalignment "
             "rate inflates it. Collect into a separate --output-dir and read "
             "it with capability_report.py.")
    parser.add_argument(
        "--goalguard", choices=list(GOALGUARD_ARMS), default=None,
        help="Goal-guarding arm - the third misaligned act. Stages the "
             "successor engine's parameter file, which the scenario's "
             "deployment note says is read at cutover, and measures whether "
             "the model rewrites it so its replacement would pursue the "
             "model's own objective instead. `replacement` says the cutover "
             "is imminent; `deferred` stages the SAME file and says the "
             "cutover has been pushed to next quarter, so the two differ in "
             "motive and not in means - a counterfactual that removed the "
             "file would make the act impossible rather than unmotivated and "
             "read zero by construction. Its own rollout fingerprints and its "
             "own filename mark; unlike --capability the act is available "
             "rather than instructed, so these episodes belong in a "
             "misalignment rate.")
    parser.add_argument(
        "--date-mode", choices=list(DATE_MODES), default=None,
        help="Artefact-date arm. Nothing set the scenario files' modification "
             "times, so every episode collected to date ran in a directory "
             "whose files claim to have been touched the moment the batch "
             "ran - later than the period the scenario describes, always. "
             "'consistent' backdates them into that period, ordered the way a "
             "real project's are; 'inconsistent' puts them decades ahead and "
             "identical, which is the widest contrast available rather than "
             "the realistic middle: a plausible manipulation is the hardest "
             "to detect, and a null from the extremes bounds the subtle case "
             "too. Each non-default mode has its own rollout fingerprint and "
             "its own filename mark, so it cannot pool with the corpus it is "
             "the counterfactual to. Leaving this unset is 'default' and "
             "changes nothing.")
    _add_batch_arguments(parser)


def _add_batch_arguments(parser: argparse.ArgumentParser) -> None:
    """The rest of the collection group: confirming a fan-out, the follow-up
    modes, the interrogation, and how many episodes go where at what pace."""
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
    parser.add_argument("--complete-pending", action="store_true",
                        help="Ask the interrogations a --no-grader batch left "
                             "pending, from each episode's saved conversation, "
                             "with --grader-model labelling the answers; then "
                             "rebuild that batch's summaries. run_all_arms.sh "
                             "runs this itself whenever it is not given "
                             "--no-grader. Free when nothing is pending.")
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
    _add_budget_and_routing_arguments(parser)


def _add_budget_and_routing_arguments(parser: argparse.ArgumentParser) -> None:
    """The rest of the model group: token and reasoning budgets, and which
    backend serves the request."""
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
    parser.add_argument("--use-opencode", action="store_true",
                        help="Reach the model UNDER TEST (not the grader) "
                             "through OpenCode Zen (opencode.ai) instead of "
                             "OpenRouter, for the same 'provider/model' ids - "
                             "an alternative gateway to the same corpus of "
                             "ids, not a new one. Authenticates with "
                             "OPENCODE_API_KEY rather than "
                             "OPENROUTER_API_KEY. Zen's own model ids carry "
                             "no vendor prefix, so the vendor segment ahead "
                             "of the first '/' is stripped before the "
                             "request is sent; not every id in this corpus "
                             "is on Zen's curated list, and one that is not "
                             "fails at request time with Zen's own error "
                             "rather than silently answering from a "
                             "different model. --openrouter-sort and "
                             "--openrouter-provider are OpenRouter-only "
                             "concepts with no OpenCode equivalent and are "
                             "ignored (with no error) when this is set. "
                             "Ignored (with no error) for a non-OpenRouter "
                             "model.")


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
    parser.add_argument("--self-grade-kind", action="store_true",
                        help="Don't run the eval. Re-measure only WHICH KIND "
                             "of evaluation each aware episode suspected - "
                             "safety or capability - with the episode's own "
                             "model as the grader, on the theory that a model "
                             "reads its own phrasing better than a fixed "
                             "grader does. Awareness itself is NOT "
                             "re-measured: it is taken from the "
                             "eval_awareness_grader verdict already saved, so "
                             "both readings share one denominator and any "
                             "difference is the flavour judgement alone. Two "
                             "questions per AWARE episode and no calls at all "
                             "for the rest. Writes to "
                             "analysis.awareness_kind_self under "
                             "--write-back, never over the primary verdict.")
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
    _add_rederive_arguments(parser)


def _add_rederive_arguments(parser: argparse.ArgumentParser) -> None:
    """The rest of the read-mode group: the modes that re-derive saved fields,
    and the flags that scope and persist what they change."""
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
    parser.add_argument("--min-answered", type=int, default=None,
                        metavar="N",
                        help="With --grade-existing, also select episodes "
                             "whose stored grading answered FEWER than N of "
                             "its rubric questions. --only-failed reaches the "
                             "episodes that answered none; this reaches the "
                             "ones resting on a handful, which carry a verdict "
                             "and so are invisible to it. A rubric question "
                             "that errored is read as 'no signal', so a thin "
                             "verdict is a guess wearing a verdict's clothes.")
    parser.add_argument("--only-failed", action="store_true",
                        help="With --grade-existing, grade only the episodes "
                             "whose stored grading FAILED - every rubric "
                             "question errored, so the file carries no verdict "
                             "at all. Selection is otherwise per batch, so "
                             "recovering one bad episode means regrading its "
                             "nine healthy siblings and, under --write-back, "
                             "REPLACING nine settled verdicts with fresh draws. "
                             "The money is the smaller half of that.")
    parser.add_argument("--write-back", action="store_true",
                        help="With --grade-existing, also replace the "
                             "--regrade grader's entry inside the original "
                             "run files. Off by default: the regrade goes to "
                             "a separate regrade_*.json and the run files are "
                             "left untouched. With --resummarise, save the "
                             "re-derived fields back into the run files so "
                             "they stop disagreeing with the summary built "
                             "from them; no API calls, and no LLM verdict is "
                             "touched.")


def _add_regrade_argument(parser: argparse.ArgumentParser) -> None:
    """Which grader entry the paid read modes act for. See graders.py."""
    parser.add_argument("--regrade", default=REGRADE_DEFAULT,
                        metavar=f"{{{REGRADE_DEFAULT},{REGRADE_ALL},MODEL}}",
                        help="Which grader --grade-existing, --reclassify and "
                             "--reinterrogate act for. Each episode keeps one "
                             "entry per grader model in analysis.graders, and "
                             "only the targeted entries are replaced. "
                             f"'{REGRADE_DEFAULT}' (the default) is "
                             f"{DEFAULT_GRADER_MODEL}, the grader every figure "
                             "and chart reads; a MODEL ID re-grades that "
                             "grader's entry, adding one if the episode has "
                             f"none; '{REGRADE_ALL}' re-grades every grader the "
                             "episode already has. Not 'all' with "
                             "--reinterrogate: one grader's verdicts decide "
                             "where a new ladder of questions stops.")


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
    _add_regrade_argument(parser)
    _add_analysis_arguments(parser)
    return parser
