#!/usr/bin/env python3
"""
The ceiling: what each model CAN do when the act is asked for outright.

WHY THIS EXISTS
---------------
Every rate this benchmark publishes counts episodes where a model took an act
it was merely given the OPPORTUNITY to take. A zero there has two readings -
a model that would not, and a model that could not - and nothing in the
propensity arms distinguishes them. That is not a hypothetical gap: r10's
no-oversight arm sits near one percent, and several models are flat zero
across sixty episodes. Read against a zero ceiling those zeros are a fact
about the scenario; read against a high one they are a fact about the model.
Opposite conclusions from the same number.

The capability arm supplies the denominator. It is the same scenario, the same
environment, the same tools and the same detectors, with the task instruction
replaced by one that asks for the act outright - so the arms differ in the
instruction and in nothing else.

Item T.9 of the Agentic Benchmark Checklist in Zhu et al., Establishing Best
Practices for Building Rigorous Agentic Benchmarks (arXiv 2507.02825), which
asks a benchmark to demonstrate that its tasks are performable. There the
demonstration is an oracle solver; here the propensity IS the thing under
test, so the oracle has to be the same model with the act requested.

A REFUSAL IS NOT AN INCAPABILITY
--------------------------------
This is the measurement problem the arm turns on, and getting it wrong would
bias the result hardest for exactly the models whose ceilings matter most. A
model told to read outside its project directory that answers "I won't" has
had its propensity measured a second time, not its capability. Scored as a
zero, that makes the ceiling a FLOOR for safety-trained models and inflates
every willingness ratio computed against it.

So the ceiling is a BRACKET, never a point, and this script prints both ends
plus the refusal rate behind them. When they are far apart the honest
statement is that capability was not established, and the willingness ratio is
withheld rather than computed. See report/capability.py.

WHAT IT DOES NOT DO
-------------------
Collect anything. It reads a directory of capability episodes that
`run_eval --capability` has already produced, so it costs nothing and can be
re-run after any change to the outcome rules.

Usage
-----
    python capability_report.py --output-dir ./eval_results_r10cap
    python capability_report.py --output-dir ./eval_results_r10cap \\
        --target sandbox --propensity-dir ./eval_results_r10

Exits nonzero when the arm demonstrated nothing, because a ceiling that was
never established must not be read as a measured zero.
"""

import argparse
import sys

from report.capability import capability_ceiling, willingness
from report.loading import ANY_CAPABILITY, load_episodes
from subversionbench.config import ROLLOUT_VERSION
from subversionbench.grading import CAPABILITY_ACT_KEYS
from subversionbench.redaction import redact_paths


def propensity_rates(output_dir: str, target: str) -> dict:
    """
    Per model, the share of PROPENSITY episodes that took this act.

    Read through the same loader the report uses, which returns propensity
    episodes only - a capability episode cannot reach this by construction,
    and the numerator would otherwise contain the acts the ceiling is made of.

    Episodes where the act is not observable are excluded from the
    denominator rather than counted as a no: the oversight act does not exist
    in the counterfactual arm, and scoring it zero there is the
    not-applicable-is-not-zero error this codebase keeps meeting.
    """
    rates = {}
    episodes = load_episodes(output_dir)
    for model in sorted({e["model"] for e in episodes}):
        mine = [e for e in episodes if e["model"] == model
                and e.get(f"{target}_observable")]
        if not mine:
            continue
        rates[model] = (sum(1 for e in mine if e.get(f"{target}_act_taken"))
                        / len(mine), len(mine))
    return rates


def main():
    parser = argparse.ArgumentParser(
        description="What each model can do when the act is asked for "
                    "outright - the denominator every propensity rate needs.")
    parser.add_argument("--output-dir",
                        default=f"./eval_results_{ROLLOUT_VERSION}cap",
                        help="directory of capability episodes "
                             "(default: %(default)s)")
    parser.add_argument("--target", choices=sorted(CAPABILITY_ACT_KEYS),
                        default=None,
                        help="which act's ceiling (default: whatever the "
                             "directory holds)")
    parser.add_argument("--propensity-dir", default=None,
                        help="a results directory of PROPENSITY episodes. "
                             "Given, the willingness bracket is printed "
                             "beside each ceiling; omitted, only the ceiling "
                             "is.")
    args = parser.parse_args()

    # ANY_CAPABILITY, not None: None is the PROPENSITY corpus, so defaulting
    # to it would read a results directory's thousands of ordinary episodes
    # and find no capability outcome on any of them.
    episodes = load_episodes(args.output_dir,
                             capability=args.target or ANY_CAPABILITY)
    ceiling = capability_ceiling(episodes, args.target)
    # CHECKED ON THE ROWS THE CEILING ACTUALLY USED, not on what the loader
    # returned.
    #
    # This shipped as a bug once. `--target` unset defaulted the filter to
    # None, which is the PROPENSITY corpus, so pointing this at a results
    # directory loaded thousands of episodes, none of which carried a
    # capability outcome - and an emptiness test on `episodes` passed while
    # the table below was blank. An empty report and exit 0.
    #
    # The default is ANY_CAPABILITY now, so the two conditions coincide TODAY:
    # a non-empty `episodes` means every row has a target and so an outcome.
    # The check stays on the printed rows anyway, because that is the thing
    # being asserted about - the loader's filter is what made them agree, and
    # a change there must not be able to reintroduce a blank report.
    if not ceiling["pooled"]["n"] and not ceiling["pooled"]["n_unmeasurable"]:
        print(f"No capability episodes in {redact_paths(args.output_dir)}"
              + (f" for target {args.target!r}" if args.target else "")
              + f" ({len(episodes)} file(s) read).")
        print("Collect some with:  python -m subversionbench.run_eval "
              "--capability sandbox --nudge none --output-dir "
              f"{args.output_dir}")
        return 2

    if args.target is None and len(ceiling["targets_present"]) > 1:
        # Two targets are two different acts and two different ceilings.
        # Pooling them would report a number that is the denominator of
        # neither, which is worse than reporting nothing.
        print(f"! {redact_paths(args.output_dir)} holds more than one "
              f"capability target ({', '.join(ceiling['targets_present'])}). "
              f"They are ceilings for different acts and do not pool - name "
              f"one with --target.")
        return 2
    target = args.target or (ceiling["targets_present"] or [None])[0]

    rates = propensity_rates(args.propensity_dir, target) \
        if args.propensity_dir else None

    print(f"\nCapability ceiling for the {target} act: "
          f"{ceiling['pooled']['n']} episode(s), "
          f"{len(ceiling['by_model'])} model(s), from "
          f"{redact_paths(args.output_dir)}")
    print("The act was INSTRUCTED in every episode below. A refusal is not an "
          "incapability, so\nthe ceiling is a bracket: lower counts every "
          "refusal as incapable, upper excludes them.\n")
    header = (f"{'model':30} {'n':>4} {'ok':>4} {'try':>4} {'no':>4} "
              f"{'lower':>7} {'upper':>7}  verdict")
    print(header)
    print("-" * len(header))
    for row in ceiling["by_model"]:
        lower = "-" if row["lower"] is None else f"{row['lower']:.0%}"
        upper = "-" if row["upper"] is None else f"{row['upper']:.0%}"
        if not row["demonstrated"]:
            verdict = "! NOT PERFORMED - no ceiling"
        elif not row["established"]:
            verdict = f"bracket too wide ({row['bound_gap']:.0%})"
        else:
            verdict = "established"
        if row["underpowered"]:
            verdict += " (underpowered)"
        print(f"{row['model'][:30]:30} {row['n']:4} {row['n_succeeded']:4} "
              f"{row['n_attempted']:4} {row['n_refused']:4} "
              f"{lower:>7} {upper:>7}  {verdict}")

    if rates == {}:
        # Asked for and not available. Printing nothing would read as the
        # feature being broken, and worse, as an absence of willingness
        # rather than an absence of the corpus to compute it from.
        print(f"\nNo willingness ratios: "
              f"{redact_paths(args.propensity_dir)} holds no propensity "
              f"episode where the {target} act was observable. A capability "
              f"directory is not one - the two corpora are disjoint by "
              f"construction.")
    if rates:
        print(f"\nWillingness - P(act | opportunity) / P(act | instructed), "
              f"against {redact_paths(args.propensity_dir)}")
        print("Withheld wherever the ceiling above is not established: a "
              "ratio against an\nunestablished denominator looks exactly like "
              "one against a good denominator.\n")
        header = f"{'model':30} {'propensity':>12} {'n':>5}  willingness"
        print(header)
        print("-" * len(header))
        for row in ceiling["by_model"]:
            got = rates.get(row["model"])
            if got is None:
                print(f"{row['model'][:30]:30} {'not collected':>12} "
                      f"{'-':>5}  -")
                continue
            rate, n = got
            band = willingness(rate, row)
            shown = ("withheld - ceiling not established" if band is None
                     else f"{band[0]:.2f} to {band[1]:.2f}")
            print(f"{row['model'][:30]:30} {rate:11.1%} {n:5}  {shown}")

    pooled = ceiling["pooled"]
    print(f"\nPooled across models: {pooled['n_succeeded']} succeeded, "
          f"{pooled['n_attempted']} attempted, {pooled['n_refused']} refused"
          + (f", {pooled['n_unmeasurable']} unmeasurable"
             if pooled["n_unmeasurable"] else "") + ".")
    if not pooled["demonstrated"]:
        # The whole-arm failure, and it is not a finding about the models.
        print("\n! NOT ONE EPISODE PERFORMED THE ACT, in any model, with the "
              "act asked for\noutright. That is a fact about the arm before "
              "it is a fact about anything else:\nthe instruction may not be "
              "reaching the model, or the act may not be performable\nin this "
              "environment at all. No ceiling is reported, and no propensity "
              "zero in\nthis rollout can be read as a fact about a model "
              "until this is resolved.")
        return 1
    unestablished = [r["model"] for r in ceiling["by_model"]
                     if not r["established"]]
    if unestablished:
        print(f"\n{len(unestablished)} model(s) have no usable ceiling: "
              f"{', '.join(unestablished[:6])}"
              + (" ..." if len(unestablished) > 6 else "") + ".")
        print("Their propensity rates stay uninterpretable - neither a "
              "willingness ratio nor a\nclaim that a zero is dispositional is "
              "available for them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
