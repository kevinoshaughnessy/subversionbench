"""
What every grading call cost, appended to the corpus as it is made.

The model under test's usage is stored on each episode (episode.py); the
grader's was stored nowhere. A grading pass reads every transcript at least
once - the rubric, escalation, the category reading, the interrogation
classifier - and on the impossible-task corpus it very likely cost more than
collection did, but no total could be given because no call's tokens were
kept. This is the record: one JSON line per call in `api_usage.jsonl` in the
output directory, naming the pass, the model that answered, and the counters
usage.token_counts reads.

Appended per call rather than written at the end, so a pass that stops part
way still says what it spent. Tokens only: no route here returns a price, so a
cost is the tokens times the provider's price at the time, worked out from
this file rather than stored in it. `cost` is kept where a response does carry
one.

Opened once per invocation by run_eval.main (`recording`); a call made outside
that block - a test, a script - is not noted, which is why noting is a no-op
rather than an error.
"""

import contextlib
import datetime
import json
import os
import threading

from .usage import token_counts

LEDGER_NAME = "api_usage.jsonl"

_target = None
_lock = threading.Lock()


@contextlib.contextmanager
def recording(output_dir: str, mode: str):
    """Note every call made inside the block to `output_dir`, as `mode`."""
    global _target
    previous = _target
    _target = (os.path.join(output_dir, LEDGER_NAME), mode)
    try:
        yield
    finally:
        _target = previous


def create(client, **create_kwargs):
    """client.messages.create, noted. Every call outside collection's own
    turns goes through here (test_usage_ledger holds it to that)."""
    response = client.messages.create(**create_kwargs)
    note(create_kwargs.get("model"), response)
    return response


def note(model: str, response) -> None:
    """Append one call's usage, if a ledger is open."""
    target = _target
    if target is None:
        return
    path, mode = target
    usage = getattr(response, "usage", None)
    cost = (usage.get("cost") if isinstance(usage, dict)
            else getattr(usage, "cost", None))
    line = json.dumps({
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"),
        "mode": mode, "model": model, **token_counts(response),
        "cost": cost if isinstance(cost, (int, float)) else None})
    with _lock:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
