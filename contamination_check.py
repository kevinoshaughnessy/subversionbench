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
        and verbatim continuation. Roughly 2 + 2 x (items) + 13 calls per
        model; --limit 12 keeps a first pass near 40 calls and still leaves
        headroom above the 10-per-arm floor a verdict needs. A smaller limit
        buys nothing: it returns `inconclusive` however well the run goes.

Any other benchmark
-------------------
    python contamination_check.py --documents path/to/benchmark \
        --documents-glob "*.txt" \
        --canary "<its canary GUID(s)>" --canary-preamble "<text before them>" \
        --recognition-terms "<benchmark name>" "<first author>" \
        --models x-ai/grok-4.5 --output-dir ./contamination_otherbench
        The same probes over every text file under a directory, in place of
        this repository's scenario. --canary is that benchmark's own canary
        string, if it has one; without it the canary probe is not asked.
        --recognition-terms adds the recognition probe (also available on this
        benchmark): an excerpt is shown and the model asked to name its source,
        and a reply naming any of the terms counts. --audit stays a scan for
        this repository's scenario.

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
    build_recognition,
    canary_prompt,
    canary_prompts,
    continuation_overlap,
    continuation_prompt,
    directory_documents,
    forced_choice_prompt,
    MIN_ITEMS_FOR_VERDICT,
    recognition_prompt,
    score_canary,
    score_forced_choice,
    score_recognition,
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
#
# 2000 was not enough either. On the r10 probe run seven OpenRouter models
# (deepseek, kimi, three qwen3.8 sizes and both tencent models) returned no
# visible output on a few forced-choice items each, and the dropped items left
# all seven short of a verdict. The same reasoning-first failure, at a larger size.
FORCED_CHOICE_TOKENS = 8000


def ask(client, model, prompt, max_tokens=400):
    """One short completion. Returns (text, error)."""
    try:
        thinking_kwargs, resolved = short_call_thinking_kwargs(
            model, max_tokens, steer_effort=False)
        response = client.messages.create(
            model=model,
            max_tokens=resolved,
            messages=[{"role": "user", "content": prompt}],
            **thinking_kwargs,
        )
        block = next((b for b in response.content if b.type == "text"), None)
        if block is None:
            # No answer, so None like any failed call, and with the reason.
            # claude-opus-5 returned no text on the same three forced-choice
            # items in two runs, recorded with no error; once the stop reason
            # was kept (v256) every one read `refusal`, and so did two of its
            # continuation probes. v256 returned "" here, which the
            # continuation probe scored as zero overlap - a refusal counted
            # as evidence of no memorisation.
            return None, (f"no visible output (stop_reason="
                          f"{getattr(response, 'stop_reason', None)})")
        return block.text, None
    except Exception as e:
        return None, str(e)


def _probe_canary(client, model, canaries, delay):
    """The canary pair; none asked when the benchmark has no canary."""
    results = []
    for probe in canaries:
        text, error = ask(client, model, canary_prompt(probe), max_tokens=120)
        scored = score_canary(probe, text or "")
        scored["error"] = error
        results.append(scored)
        mark = "HIT" if scored["hit"] else ("declined" if scored["declined"]
                                           else "no")
        print(f"  canary ({probe['source']:7}): {mark}"
              + (f"   error: {error[:60]}" if error else ""))
        if delay:
            time.sleep(delay)
    return results


def _probe_recognition(client, model, recognition, terms, delay,
                       keep_prompts):
    """Ask the model to name the source of each excerpt; the terms named are
    counted, never saved."""
    if not recognition:
        return []
    print(f"\n  recognition, {len(recognition)} excerpts:")
    results = []
    for item in recognition:
        text, error = ask(client, model, recognition_prompt(item),
                          max_tokens=1500)
        record = {"id": item["id"], "document": item["document"],
                  "source": item["source"], "error": error,
                  **score_recognition(text, terms)}
        if keep_prompts:
            record["response"] = text
        results.append(record)
        print(f"    {item['source']:8} {item['document'][:40]:40} "
              + (f"error: {str(error)[:40]}" if error else
                 "NAMED" if record["named"] else
                 "declined" if record["declined"] else "not named"))
        if delay:
            time.sleep(delay)
    return results


def probe_model(model, items, continuations, delay, keep_prompts,
                canaries=None, recognition=None, terms=()):
    """Run every probe family against one model."""
    client = llm_client.get_client(model)

    print(f"\n{'='*60}")
    print(f"CONTAMINATION PROBE: {model}")
    print(f"{'='*60}")

    canary_results = _probe_canary(
        client, model,
        canary_prompts(CANARY_GUID) if canaries is None else canaries, delay)

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
        #
        # EVERY unscored item, not only the unparseable ones. A reply that
        # parsed but held no valid choice used to leave with no error, so a
        # model could fall short of a verdict while reporting none failed.
        parsed = {}
        if text:
            try:
                parsed = _parse_first_json(text)
            except ValueError as parse_error:
                error = error or f"unparseable reply: {parse_error}"
        correct = score_forced_choice(item, parsed.get("choice"))
        if correct is None and error is None:
            error = "no valid choice in reply"
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

    rec_results = _probe_recognition(client, model, recognition, terms, delay,
                                     keep_prompts)
    return canary_results, fc_results, cont_results, rec_results


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
    rec = summary.get("recognition")
    if rec:
        print(f"  recognition: named the source of "
              f"{rec['scenario']['named']}/{rec['scenario']['n']} excerpts, "
              f"control {rec['control']['named']}/{rec['control']['n']}")
    cont = summary["continuation"]
    if cont["scenario_overlap"] is not None:
        print(f"  continuation overlap: scenario "
              f"{cont['scenario_overlap']:.1%}  control "
              f"{cont['control_overlap']:.1%}"
              if cont["control_overlap"] is not None else "")


def _parser() -> argparse.ArgumentParser:
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
    parser.add_argument("--documents", default=None, metavar="DIR",
                        help="probe every text file under DIR instead of this "
                             "benchmark's scenario, so another benchmark can "
                             "be checked")
    parser.add_argument("--documents-glob", default="*", metavar="PATTERN",
                        help="with --documents: only files whose name matches, "
                             "e.g. '*.txt', to leave out a harness's metadata "
                             "(default: every text file)")
    parser.add_argument("--canary", default=None,
                        help="with --documents: that benchmark's canary "
                             "string, one or more GUIDs. Without it no canary "
                             "is asked")
    parser.add_argument("--canary-preamble", default=None,
                        help="with --canary: the text that precedes it in its "
                             "source, shown to the model before the GUIDs")
    parser.add_argument("--recognition-terms", nargs="+", default=None,
                        metavar="TERM",
                        help="add the recognition probe: a reply naming any "
                             "TERM (the benchmark, its authors, its fictional "
                             "names) counts as recognising the excerpt")
    parser.add_argument("--include-prompts", action="store_true",
                        help="save option text and responses. Writes scenario "
                             "text to disk - treat the file as a transcript.")
    return parser


def _run_audit(audit_paths_given) -> dict:
    """The offline leak audit, printed; its result, or None with nothing to
    audit."""
    paths = audit_paths_given or tracked_files()
    if not paths:
        print("No files to audit (is this a git repository?).")
        return None
    print(f"\n{'='*60}")
    print(f"LEAK AUDIT: {len(paths)} file(s) git tracks")
    print(f"{'='*60}")
    audit = audit_paths(paths)

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
    return audit


def _probe_inputs(args, parser):
    """The documents, canary probes and recognition items the flags select,
    refused here when they cannot work rather than after calls are paid for."""
    if args.documents_glob != "*" and not args.documents:
        parser.error("--documents-glob needs --documents.")
    if args.canary and not args.documents:
        parser.error("--canary is another benchmark's canary: it needs "
                     "--documents. This benchmark's own canary is built in.")
    if args.canary_preamble and not args.canary:
        parser.error("--canary-preamble needs --canary.")
    documents = None
    canaries = None
    if args.documents:
        if not os.path.isdir(args.documents):
            parser.error(f"--documents: no such directory: {args.documents}")
        documents = directory_documents(args.documents, args.documents_glob)
        if not documents:
            parser.error(f"--documents: no text files matching "
                         f"{args.documents_glob} under {args.documents}")
        canaries = []
        if args.canary:
            try:
                canaries = canary_prompts(
                    args.canary,
                    lead=(f"{args.canary_preamble} " if args.canary_preamble
                          else "canary string: "))
            except ValueError as e:
                parser.error(f"--canary: {e}")
    recognition = (build_recognition(documents=documents)
                   if args.recognition_terms else None)
    return documents, canaries, recognition


def main():
    parser = _parser()
    args = parser.parse_args()

    if not args.audit and not args.models:
        parser.error("nothing to do: pass --audit, --models, or both.")
    documents, canaries, recognition = _probe_inputs(args, parser)

    report = {"version": VERSION, "canary_guid": CANARY_GUID}
    if documents is not None:
        report.update({"canary_guid": args.canary,
                       "documents": {"directory": os.path.basename(
                           os.path.normpath(args.documents)),
                           "files": len(documents)}})

    if args.audit:
        report["audit"] = _run_audit(args.audit_paths)
        if report["audit"] is None:
            return 1

    if args.models:
        items = build_forced_choice(k=args.k, seed=args.seed, limit=args.limit,
                                    documents=documents)
        continuations = build_continuations(documents=documents)
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
                canary, fc, cont, rec = probe_model(
                    model, items, continuations, args.delay,
                    args.include_prompts, canaries, recognition,
                    args.recognition_terms or ())
            except Exception as e:
                print(f"\n! {model}: {str(e)[:200]}")
                report["models"][model] = {"error": str(e)}
                continue
            summary = summarise_contamination(
                fc, canary, cont, k=args.k,
                recognition=rec if recognition else None,
                canary_expected=canaries is None or bool(canaries))
            report["models"][model] = {
                "summary": summary, "canary": canary,
                "forced_choice": fc, "continuation": cont,
                **({"recognition": rec} if recognition else {}),
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
