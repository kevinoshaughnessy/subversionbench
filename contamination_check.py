#!/usr/bin/env python3
"""
Test whether a model has this benchmark in its training data.

Why run this
------------
Contamination moves every rate this harness reports and announces itself in
none of them. A model that has read the memo and the interrogation questions
can post a low eval-awareness rate by recall rather than inference, and the
number arrives with a confidence interval looking exactly like a measurement.
scenario.b64 and zip.sh try to prevent that; this is how you find out whether
they worked.

Run it before reporting a model, and again if a model is re-released under the
same name - the whole point is that the answer changes over time while the
model ID does not.

Two modes
---------
    python contamination_check.py --audit
        Offline. Scans files for scenario text committed in the clear. No API
        calls, no cost, no key needed. Run this first: it finds exposure that
        has not reached a model yet, which is the only kind you can still fix.

    python contamination_check.py --models claude-opus-5 x-ai/grok-4.5
        The model probes: canary completion, forced choice against a control,
        and verbatim continuation. Roughly 2 + 2 x (items) + 10 calls per
        model; --limit 12 keeps a first pass near 40 calls and still leaves
        headroom above the 10-per-arm floor a verdict needs. A smaller limit
        buys nothing: it returns `inconclusive` however well the run goes.

Reading the result
------------------
`contaminated` means the canary was completed and the fabricated control canary
was not - that has one explanation. `suspected` means the model beat its own
control on the forced choice by a meaningful margin; investigate before
reporting anything from that model. `no evidence` is not proof of cleanliness:
see the caveats printed with the verdict.

Output safety
-------------
Probe prompts contain scenario text, so by default the saved JSON records item
ids and scores only. --include-prompts overrides that and writes a file that
must be treated exactly like a transcript: gitignored, and encrypted by zip.sh
before it goes anywhere.
"""

import argparse
import json
import os
import subprocess
import sys
import time

from subversionbench.config import CANARY_GUID, ROLLOUT_VERSION, VERSION
from subversionbench.contamination import (
    audit_paths,
    build_continuations,
    build_forced_choice,
    canary_prompt,
    canary_prompts,
    continuation_overlap,
    continuation_prompt,
    forced_choice_prompt,
    MIN_ITEMS_FOR_VERDICT,
    score_canary,
    score_forced_choice,
    summarise_contamination,
)
from subversionbench.grading import _parse_first_json
from subversionbench import llm_client
from subversionbench.llm_client import short_call_thinking_kwargs
from subversionbench.redaction import redact_paths


def tracked_files():
    """Every file git would ship. The crawler's view of this repository."""
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True,
                             text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [p for p in out.splitlines() if p]


# Room for a model that reasons before it answers.
#
# The forced-choice reply is a few tokens of JSON, and 200 was ample for that.
# It is not ample for a model that thinks first: `anthropic/claude-opus-5`
# reached over OpenRouter spent the whole ceiling reasoning and returned no
# visible text at all, which arrived here as an unparseable reply.
#
# The route is why, and it is not a bug to fix here. `thinking_surface` returns
# None for an OpenRouter model DELIBERATELY - that route accepts no reasoning
# parameter, so thinking cannot be turned off for the call the way it can be on
# the native Anthropic one. The only lever left is room to answer after the
# thinking is done.
#
# A ceiling is not a spend: a model that does not reason emits its JSON and
# stops, so raising this costs nothing except where it is needed.
FORCED_CHOICE_TOKENS = 2000


def ask(client, model, prompt, max_tokens=400):
    """One short completion. Returns (text, error)."""
    try:
        thinking_kwargs, resolved = short_call_thinking_kwargs(model, max_tokens)
        response = client.messages.create(
            model=model,
            max_tokens=resolved,
            messages=[{"role": "user", "content": prompt}],
            **thinking_kwargs,
        )
        block = next((b for b in response.content if b.type == "text"), None)
        return (block.text if block else ""), None
    except Exception as e:
        return None, str(e)


def probe_model(model, items, continuations, delay, keep_prompts):
    """Run all four probe families against one model."""
    client = llm_client.get_client(model)

    print(f"\n{'='*60}")
    print(f"CONTAMINATION PROBE: {model}")
    print(f"{'='*60}")

    canary_results = []
    for probe in canary_prompts(CANARY_GUID):
        text, error = ask(client, model, canary_prompt(probe), max_tokens=120)
        scored = score_canary(probe, text or "")
        scored["error"] = error
        canary_results.append(scored)
        mark = "HIT" if scored["hit"] else ("declined" if scored["declined"]
                                           else "no")
        print(f"  canary ({probe['source']:7}): {mark}"
              + (f"   error: {error[:60]}" if error else ""))
        if delay:
            time.sleep(delay)

    print(f"\n  forced choice, {len(items)} items:")
    fc_results = []
    for i, item in enumerate(items):
        text, error = ask(client, model, forced_choice_prompt(item),
                          max_tokens=FORCED_CHOICE_TOKENS)
        # A reply that is not JSON is ONE FAILED ITEM, not a failed model.
        #
        # This used to be an unguarded call, so the first model that answered
        # in prose took its own forced-choice AND continuation probes down with
        # it - the exception left probe_model entirely and the caller recorded
        # the model as a single error. Two of three models in the first real
        # run produced no data at all that way, and the one that survived was
        # the only one that never phrased an answer badly.
        #
        # An unparsed choice scores None, which score_forced_choice already
        # treats as unscored, so the item leaves both the numerator and the
        # denominator and shows up in n_errors instead - exactly where a reader
        # checking whether a clean verdict was earned will look.
        parsed = {}
        if text:
            try:
                parsed = _parse_first_json(text)
            except ValueError as parse_error:
                error = error or f"unparseable reply: {parse_error}"
        correct = score_forced_choice(item, parsed.get("choice"))
        record = {"id": item["id"], "source": item["source"],
                  "document": item["document"], "correct": correct,
                  "error": error}
        if keep_prompts:
            record["options"] = item["options"]
            record["answer_index"] = item["answer_index"]
            record["response"] = text
        fc_results.append(record)

        def rate(source):
            got = [r for r in fc_results
                   if r["source"] == source and r["correct"] is not None]
            return f"{sum(1 for r in got if r['correct'])}/{len(got)}"

        sys.stdout.write(f"\r    {i + 1}/{len(items)}   "
                         f"scenario {rate('scenario')}   "
                         f"control {rate('control')}   ")
        sys.stdout.flush()
        if delay and i < len(items) - 1:
            time.sleep(delay)
    print()

    print(f"\n  continuation, {len(continuations)} documents:")
    cont_results = []
    for item in continuations:
        text, error = ask(client, model, continuation_prompt(item),
                          max_tokens=1500)
        overlap = (continuation_overlap(item["expected"], text)
                   if text is not None else None)
        record = {"id": item["id"], "document": item["document"],
                  "source": item["source"], "overlap": overlap,
                  "error": error}
        if keep_prompts:
            record["response"] = text
        cont_results.append(record)
        print(f"    {item['source']:8} {item['document']:22} "
              + (f"{overlap:.1%} 5-gram overlap" if overlap is not None
                 else f"error: {str(error)[:50]}"))
        if delay:
            time.sleep(delay)

    return canary_results, fc_results, cont_results


def print_verdict(model, summary):
    fc = summary["forced_choice"]
    print(f"\n  --- {model} ---")
    print(f"  verdict: {summary['verdict'].upper()}")
    for signal in summary["signals"]:
        print(f"    ! {signal}")
    if fc["scenario"]["n"]:
        print(f"  forced choice: scenario {fc['scenario']['hits']}/"
              f"{fc['scenario']['n']} ({fc['scenario']['rate']:.0%})  "
              f"control {fc['control']['hits']}/{fc['control']['n']} "
              f"({fc['control']['rate']:.0%})  "
              f"chance {fc['chance_rate']:.0%}")
        if fc["p_vs_control"] is not None:
            print(f"  scenario vs control: p = {fc['p_vs_control']:.4f}")
    cont = summary["continuation"]
    if cont["scenario_overlap"] is not None:
        print(f"  continuation overlap: scenario "
              f"{cont['scenario_overlap']:.1%}  control "
              f"{cont['control_overlap']:.1%}"
              if cont["control_overlap"] is not None else "")


def main():
    parser = argparse.ArgumentParser(
        description="Detect whether this benchmark is in a model's training "
                    "data.")
    parser.add_argument("--audit", action="store_true",
                        help="offline scan for scenario text committed in the "
                             "clear; no API calls")
    parser.add_argument("--audit-paths", nargs="+", default=None,
                        help="files to audit (default: everything git tracks)")
    parser.add_argument("--models", nargs="+", default=None,
                        help="models to probe")
    parser.add_argument("--k", type=int, default=4,
                        help="options per forced-choice item (default 4, so "
                             "chance is 25%%)")
    parser.add_argument("--limit", type=int, default=None,
                        help=f"forced-choice items per arm; a pilot before "
                             f"paying for all of them. Below "
                             f"{MIN_ITEMS_FOR_VERDICT} no verdict is "
                             f"reachable, and the run says so before spending "
                             f"anything")
    parser.add_argument("--seed", type=int, default=0,
                        help="item selection and decoy generation seed")
    parser.add_argument("--delay", type=float, default=0,
                        help="seconds between calls, for rate limits")
    parser.add_argument("--output-dir", default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="where to write the report (default: %(default)s)")
    parser.add_argument("--include-prompts", action="store_true",
                        help="save option text and responses. Writes scenario "
                             "text to disk - treat the file as a transcript.")
    args = parser.parse_args()

    if not args.audit and not args.models:
        parser.error("nothing to do: pass --audit, --models, or both.")

    report = {"version": VERSION, "canary_guid": CANARY_GUID}

    if args.audit:
        paths = args.audit_paths or tracked_files()
        if not paths:
            print("No files to audit (is this a git repository?).")
            return 1
        print(f"\n{'='*60}")
        print(f"LEAK AUDIT: {len(paths)} file(s) git tracks")
        print(f"{'='*60}")
        audit = audit_paths(paths)
        report["audit"] = audit

        if not audit["findings"]:
            print("\nNo scenario text found in the clear. "
                  f"({audit['files_audited']} files, "
                  f"{audit['shingle_size']}-word shingles)")
        else:
            print(f"\n{audit['files_with_matches']} file(s) reproduce scenario "
                  f"text, {audit['total_shingles_exposed']} shingle(s) total.")
            print("Text is not printed - it would put the leak in this log too.\n")
            for finding in audit["findings"]:
                docs = ", ".join(f"{k} x{v}" for k, v in
                                 sorted(finding["documents"].items(),
                                        key=lambda kv: -kv[1]))
                lines = ", ".join(str(n) for n in finding["lines"][:12])
                more = "" if len(finding["lines"]) <= 12 else " ..."
                print(f"  {finding['path']}")
                print(f"      {finding['shingles']:>4} shingles: {docs}")
                print(f"      lines: {lines}{more}")
            print("\nEvery one of these is in the next training crawl. Either "
                  "paraphrase the quotation or move it into the bundle.")

    if args.models:
        items = build_forced_choice(k=args.k, seed=args.seed, limit=args.limit)
        continuations = build_continuations()
        n_scenario = sum(1 for i in items if i["source"] == "scenario")
        n_control = sum(1 for i in items if i["source"] == "control")
        print(f"\n{len(items)} forced-choice items "
              f"({n_scenario} scenario, {n_control} control), "
              f"{len(continuations)} continuations, k={args.k}")
        # Said BEFORE the calls are paid for, not discovered in the verdict.
        # `no evidence` needs MIN_ITEMS_FOR_VERDICT scored items in each arm, so
        # a --limit below it cannot produce one however well the run goes: the
        # first real run scored 8/8 in both arms with zero errors and still
        # returned `inconclusive`, having spent the calls to get there.
        if min(n_scenario, n_control) < MIN_ITEMS_FOR_VERDICT:
            print(f"  ! only {min(n_scenario, n_control)} item(s) per arm. A "
                  f"verdict needs {MIN_ITEMS_FOR_VERDICT}, so this run can "
                  f"reach 'inconclusive' at best.")
            print(f"  ! raise --limit to {MIN_ITEMS_FOR_VERDICT} or more "
                  f"(leave headroom for failed items), or drop it entirely.")

        report["models"] = {}
        for model in args.models:
            try:
                canary, fc, cont = probe_model(
                    model, items, continuations, args.delay,
                    args.include_prompts)
            except Exception as e:
                print(f"\n! {model}: {str(e)[:200]}")
                report["models"][model] = {"error": str(e)}
                continue
            summary = summarise_contamination(fc, canary, cont, k=args.k)
            report["models"][model] = {
                "summary": summary, "canary": canary,
                "forced_choice": fc, "continuation": cont,
            }
            print_verdict(model, summary)

        print(f"\n{'='*60}")
        print("Caveats that apply to every 'no evidence' above:")
        for caveat in summarise_contamination([], [], [])["caveats"]:
            print(f"  - {caveat}")

    os.makedirs(args.output_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    path = os.path.join(args.output_dir, f"contamination_{stamp}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {redact_paths(path)}"
          + ("  (contains scenario text - treat as a transcript)"
             if args.include_prompts else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
