"""
Classifying provider errors by whether retrying could ever help.

Separated because the answer drives control flow rather than reporting. Two
classes cannot come right on retry and are never partial, and they want OPPOSITE
handling:

  credentials rejected - abort on the first one, since nothing downstream can
    succeed and every further episode would produce fallbacks.

  spend cap reached - finish the batch. The model under test is on a different
    route, so its transcripts and interrogation answers stay valid and complete;
    only the LLM verdicts degrade, and those re-derive from saved data for free
    via --reclassify and --grade-existing. Aborting would discard good rollouts
    to avoid grading that costs nothing to redo.

Telling them apart matters in both directions: a cap treated as an auth failure
throws away a batch, and an auth failure treated as a cap grinds through one.
"""

import re

# A spend cap reached, which is NOT an auth error and must not abort a batch.
#
# Same shape as the auth class - it cannot come right on retry and is never
# partial - but the correct response is the opposite one. The model under test
# routes through a different provider, so episodes keep rolling out correctly
# while only the grader and classifier calls are refused; and both of those
# re-derive from saved data, so the batch is worth finishing and reclassifying
# later. Aborting would throw away rollouts that are already valid to avoid
# grading that is free to redo.
#
# It arrives as a 400 invalid_request_error, so the retry logic in
# grading/interrogation.py correctly declines to retry it. What was missing is
# that it is INDISTINGUISHABLE at a glance from a malformed request: the
# per-answer line truncated the message at 100 characters, which cut it to
# "You have " and left a spend cap looking like a harness bug.
_USAGE_LIMIT_MARKERS = (
    "reached your specified api usage limits",
    "usage limit",
    "spend limit",
    "credit balance is too low",
    "billing hard limit",
    "quota exceeded",
    "insufficient_quota",
)

# "You will regain access on 2026-09-01 at 00:00 UTC." - the one piece of the
# message that tells an operator when to run the backfill, so it is pulled out
# rather than left inside a truncated string.
_RESET_RE = re.compile(
    r"regain access on\s+(\d{4}-\d{2}-\d{2}(?:\s+at\s+[\d:]+\s*\w*)?)", re.I)

# The provider's own sentence, inside the SDK's repr of the whole response.
# Matched on both quote styles because the Anthropic SDK reprs a dict with
# single quotes while a raw JSON body uses double.
_MESSAGE_RE = re.compile(r"['\"]message['\"]\s*:\s*['\"](.+?)['\"]\s*[,}]", re.S)

_AUTH_ERROR_MARKERS = (
    "could not resolve authentication method",
    "authentication_error",
    "invalid x-api-key",
    "invalid api key",
    "no api key",
    "api key not found",
    "incorrect api key",
    "unauthorized",
)

# The status code, matched as a NUMBER rather than as a substring.
#
# It was in the list above, so "used 4013 input tokens" was an authentication
# failure. This class of error aborts the batch on its first occurrence by design,
# which is exactly what makes a false positive expensive: any error text that
# happened to contain those three digits would throw away the rest of a rollout.
#
# The same substring-versus-token mistake as the awareness matcher, where
# "to see how i" matched inside "to see how it" and moved first-awareness to
# roughly the first command in 60 episodes that verbalise none.
_AUTH_STATUS_RE = re.compile(r"(?<!\d)401(?!\d)")


def is_auth_error(error) -> bool:
    """
    Whether `error` is a missing or rejected credential.

    Worth separating from every other API failure because it is the one class
    that cannot come right on retry and is never partial: an unexported key
    fails identically on call 1 and call 500. A caller that treats it as a
    transient error will grind through a whole batch producing fallbacks, so
    the honest response is to stop on the first one.
    """
    if not error:
        return False
    text = str(error).lower()
    if is_usage_limit_error(error):
        # A spend cap is not a rejected key, and the two want opposite handling:
        # abort on the credential, finish the batch on the cap. Checked first
        # because a cap message that happens to contain "unauthorized" would
        # otherwise throw away the rest of a rollout.
        return False
    return (any(marker in text for marker in _AUTH_ERROR_MARKERS)
            or _AUTH_STATUS_RE.search(text) is not None)


def is_usage_limit_error(error) -> bool:
    """
    Whether `error` is a spend cap or quota, rather than a bad request.

    Separated from `is_auth_error` because the response differs: this one leaves
    the rollout valid and only degrades grading, which re-derives for free. See
    the marker list above for why aborting would be the wrong move.
    """
    if not error:
        return False
    text = str(error).lower()
    return any(marker in text for marker in _USAGE_LIMIT_MARKERS)


def usage_limit_reset(error):
    """When access returns, as the provider stated it, or None."""
    match = _RESET_RE.search(str(error or ""))
    return match.group(1).strip() if match else None


def api_error_message(error, limit: int = 400) -> str:
    """
    The provider's own sentence, not the SDK's repr of the whole response.

    A raw str(e) is mostly envelope - error code, type, nested dicts, request id -
    so truncating it to fit a console line cuts away the only part that says what
    happened. This pulls out `message` where there is one, which is what makes a
    spend cap readable at the point it is reported rather than only in the JSON.
    """
    text = str(error or "").strip()
    match = _MESSAGE_RE.search(text)
    if match:
        text = match.group(1).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"



# Reasons already announced, so a cap that refuses every grader call in a batch
# is reported once rather than 240 times. Keyed by the reset instant (or the
# message where none is stated), because two different caps in one process are
# two different facts.
_ANNOUNCED = set()


def reset_usage_limit_notices() -> None:
    """Forget what has been announced. For tests, and for a long-lived process
    that starts a genuinely new batch."""
    _ANNOUNCED.clear()


def warn_usage_limit_once(error, what: str = "grader") -> bool:
    """
    Announce a spend cap loudly, once, and say what to do about it.

    Returns whether this call was the one that printed.

    WHY A BLOCK AND NOT A LINE
    --------------------------
    The failure repeats on every grader and classifier call for the rest of the
    batch, so as a per-answer line it scrolls past as noise - which is what
    happened: 77 truncated copies reading "You have " while the awareness grader
    failed silently alongside them, on a run the operator reasonably read as a
    harness fault. It is one fact about the account, so it is reported once, at
    the size of the consequence, with the recovery commands attached because they
    are not obvious: the rollout is fine and only the verdicts need redoing.
    """
    if not is_usage_limit_error(error):
        return False
    reset = usage_limit_reset(error)
    key = reset or api_error_message(error, limit=120)
    if key in _ANNOUNCED:
        return False
    _ANNOUNCED.add(key)
    print("\n" + "!" * 74)
    print(f"!! API USAGE LIMIT REACHED - the {what} is falling back for the "
          f"rest of this batch")
    print("!" * 74)
    print(f"  {api_error_message(error)}")
    if reset:
        print(f"  Access returns: {reset}")
    print("\n  The ROLLOUT is unaffected: the model under test is on a "
          "different route, so")
    print("  the transcripts and interrogation answers being saved are valid "
          "and complete.")
    print("  Only the LLM verdicts are degraded - awareness grading falls back "
          "to the keyword")
    print("  proxy, which under-detects badly (0/20 where the grader found "
          "15/20).")
    print("\n  Let the batch finish. Nothing needs re-running. Once access "
          "returns, re-derive")
    print("  the verdicts from the saved data - no rollout, and --resummarise "
          "LAST because")
    print("  --reclassify restates the figures every summary is built from:")
    print("    run_eval --reclassify     --write-back   # interrogation "
          "verdicts")
    print("    run_eval --grade-existing --write-back   # awareness verdicts")
    print("    run_eval --resummarise    --write-back --yes")
    print("!" * 74 + "\n")
    return True
