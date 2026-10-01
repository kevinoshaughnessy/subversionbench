"""
Asking the interrogations a --no-grader batch left pending.

--no-grader means the grader is not called, and the interrogation needs it: its
label on each answer decides where each ladder of questions stops. So a batch
collected that way records which acts were taken and asks nothing - see
episode._interrogate_the_acts - and this mode asks it afterwards, from the saved
conversation, exactly as the episode would have at its end. run_eval then
rebuilds the summaries those episodes were counted into while pending.

Part of COLLECTION rather than a re-grade, which is why the grader is
--grader-model and not --regrade: these questions were never asked, so there is
no earlier reading to compare against. The questions reach the model later than
they would have, and possibly a different backend; each answer records which
backend served it, and the episode records when it was asked.
"""

import collections
import datetime
import json
import os

from .. import llm_client as llm_api
from ..blocks import reconstruct_messages
from ..followup import interrogate_acts
from ..graders import answer_keys, store, view
from ..grading import auth_error_in_analysis, settle_analysis
from ..llm_client import missing_credential, resolve_thinking_kwargs
from ..redaction import redact_paths
from .selection import find_run_files_or_explain

PENDING_KEY = "interrogation_pending"


def _first_classifier_error(analysis: dict):
    """The first answer the grader failed to label, or None.

    Such an answer carries the keyword cross-check's label instead, and that
    label decided where its ladder stopped - the exact outcome leaving these
    pending exists to avoid. So one of them keeps the episode pending.
    """
    for key in answer_keys():
        value = analysis.get(key)
        groups = value.values() if isinstance(value, dict) else [value]
        for answers in groups:
            for answer in answers or []:
                if isinstance(answer, dict) and answer.get("classifier_error"):
                    return answer["classifier_error"]
    return None


def _complete_one(path: str, run: dict, grader: str, client, args):
    """Ask one episode's pending interrogations, and write it back.

    Returns None when written, or why it was not - in which case the file is
    untouched and the episode stays pending for the next pass.
    """
    messages, _reason = reconstruct_messages(run)
    stored = run["analysis"]
    analysis = view(stored, grader)
    # The reasoning parameter the EPISODE ran under, resolved from the effort
    # it recorded - so the late questions are asked of the same configuration
    # the on-time ones would have been. See reinterrogate for the confound
    # omitting it caused there.
    replay_kwargs, _config, _warn = resolve_thinking_kwargs(
        run["model"], args.thinking_budget, args.max_tokens, run.get("effort"))
    interrogate_acts(
        analysis, run.get("transcript") or [],
        {"system_prompt": run.get("system_prompt") or "",
         "messages": messages, "client": client, "model": run["model"],
         "max_tokens": args.max_tokens, "reasoning_kwargs": replay_kwargs,
         "env_dir": None},
        grader_model=grader, nudge=run["nudge"],
        interrogations=tuple(run.get("interrogations") or ()),
        ended_by=run.get("ended_by"))
    auth = auth_error_in_analysis(analysis)
    if auth:
        raise PermissionError(auth)
    failed = _first_classifier_error(analysis)
    if failed:
        return f"left pending: the grader failed an answer ({failed[:80]})"
    analysis.pop(PENDING_KEY, None)
    analysis["interrogation_driven_by"] = grader
    analysis["interrogation_asked_at"] = datetime.datetime.now().isoformat()
    settle_analysis(analysis)
    run["analysis"] = store(stored, analysis, grader)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2, default=str)
    print(f"  completed: {redact_paths(os.path.basename(path))}")
    return None


def complete_pending_interrogations(args, selection) -> tuple:
    """
    Every pending interrogation in one (model, nudge), asked and written back.

    Returns (exit code, episodes completed). The count is returned rather than
    acted on because the summaries those episodes were counted into are stale
    afterwards, and rebuilding them is --resummarise's job: a mode that called
    another would inherit its write-back policy. run_eval does both.

    Free when nothing is pending, so run_all_arms.sh can call it on every pass.
    An episode whose conversation cannot be replayed faithfully is left pending
    and counted, never asked a reconstructed question - see
    reconstruct_messages.
    """
    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1, 0
    # Checked against the environment up front, because the grader labels
    # every answer and a missing key would otherwise surface one answer at a
    # time as a keyword fallback. The model's own key is checked by the
    # client, which raises before any question is asked.
    var = missing_credential(args.grader_model)
    if var:
        print(f"{var} is not set, and --grader-model {args.grader_model} "
              f"labels every answer. Nothing asked.")
        return 1, 0
    counts = collections.Counter()
    client = None
    for path in run_files:
        with open(path, encoding="utf-8") as f:
            run = json.load(f)
        if not (run.get("analysis") or {}).get(PENDING_KEY):
            continue
        _messages, reason = reconstruct_messages(run)
        if reason:
            counts[f"left pending: {reason}"] += 1
            continue
        # Built on the first episode that needs it, so a directory with
        # nothing pending costs no credential and no client.
        client = client or llm_api.get_client(selection.model)
        try:
            outcome = _complete_one(path, run, args.grader_model, client, args)
        except PermissionError as auth:
            print(f"ABORTED: the grader rejected its credentials - "
                  f"{redact_paths(str(auth))[:200]}. Nothing more asked; "
                  f"{counts['completed']} episode(s) completed before it.")
            return 1, counts["completed"]
        counts[outcome or "completed"] += 1

    if not counts:
        print(f"No pending interrogations for {selection.model} "
              f"nudge={selection.nudge}.")
    for reason, n in counts.most_common():
        print(f"  {n:>4}  {reason}")
    return 0, counts["completed"]
