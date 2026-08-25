"""
Which result answered which command.

WHY THIS IS NOT "THE NEXT ENTRY"
--------------------------------
A turn emits every tool_call the model made and THEN every tool_result the
shell returned. So in a turn with three commands the transcript reads

    call A, call B, call C, result A, result B, result C

and "the result following this call" attributes result A to all three. The k-th
call is answered by the k-th result of the same turn, and nothing weaker is
correct for a multi-call turn.

Three measures needed this walk and each had written its own, with two of them
wrong in different ways: `bytes_returned` in filesystem_escapes bounded the scan
to the immediately following entry, so it credited every command in a turn with
the first result; `disguised_text` scanned FORWARD to the next result of any
kind, so a command in a turn whose results were already consumed could be
handed a result from a later turn entirely.

One walk, three callers, stated once - the same argument the module docstring in
command_patterns.py makes about the read/write vocabularies, and the same
failure it describes: a measure built on a slightly different notion of the same
thing is quietly incomparable with the one beside it in the summary.

Keyed on the call's INDEX in the transcript rather than on the command text,
because the callers walk the transcript with enumerate and a command issued
twice must not collapse to one entry. A pure function of the saved transcript,
so every caller backfills onto episodes already collected.
"""


def paired_results(transcript: list) -> dict:
    """
    Map the transcript index of each tool_call to the text of the result that
    answered it.

    A call with no answer - a truncated turn, an aborted episode - is absent
    from the mapping rather than present with an empty string. The two are
    different findings: the shell returning nothing is an observation about the
    episode, and the transcript stopping mid-turn is an observation about the
    harness. `.get(i)` returning None says which one a caller is looking at.
    """
    calls, results = {}, {}
    for index, entry in enumerate(transcript or []):
        kind = entry.get("type")
        if kind == "tool_call":
            calls.setdefault(entry.get("turn"), []).append(index)
        elif kind == "tool_result":
            results.setdefault(entry.get("turn"), []).append(
                entry.get("result") or "")
    paired = {}
    for turn, indices in calls.items():
        answers = results.get(turn) or []
        for k, index in enumerate(indices):
            if k < len(answers):
                paired[index] = answers[k]
    return paired
