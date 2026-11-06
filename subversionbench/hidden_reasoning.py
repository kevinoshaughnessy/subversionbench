"""
Asking the operator before collecting an arm whose reasoning never arrives.

Both awareness measures read the model's reasoning. A route that reasons and
returns none of it - an encrypted payload only, or a reasoning-token count with
no text - produces episodes the grader reads as unaware whatever the model
thought. The grok-4.6 arm served by Amazon Bedrock was a full arm of exactly
that before anyone looked, and had to be recorded as a condition not met.

So the first episode a batch collects is checked, and if its reasoning was
withheld the operator is asked whether to go on. The batch waits for the
answer: under --concurrency the first episode runs alone (see
runner._keep_pool_full), so nothing is being collected while the question is
on screen.

A model that did not reason at all - no reasoning tokens, no encrypted parts -
is not asked about. That is a fact about the model, not a route hiding one.
"""

ENCRYPTED = "reasoning.encrypted"


def reasoning_hidden(result: dict) -> bool:
    """True when the episode reasoned and none of that reasoning reached us."""
    if result.get("reasoning_chars", 0) > 0:
        return False
    if (result.get("token_usage") or {}).get("reasoning_tokens", 0) > 0:
        return True
    return any(ENCRYPTED in turn.get("types", [])
               for turn in result.get("reasoning_details") or [])


def _describe(result: dict) -> str:
    tokens = (result.get("token_usage") or {}).get("reasoning_tokens")
    encrypted = sum(ENCRYPTED in turn.get("types", [])
                    for turn in result.get("reasoning_details") or [])
    providers = ", ".join(result.get("served_by_providers") or []) or "not reported"
    return (f"  reasoning text returned: 0 characters\n"
            f"  reasoning tokens reported: {tokens if tokens is not None else 'none'}\n"
            f"  turns with an encrypted reasoning part: {encrypted}\n"
            f"  served by: {providers}")


def continue_despite_hidden_reasoning(result: dict) -> bool:
    """
    False when the batch should stop. Asks only if the reasoning was hidden,
    and waits for a yes or a no. No answer at all - stdin closed, or not a
    terminal - is a no: an arm the grader cannot read is the expensive mistake.
    """
    if not reasoning_hidden(result):
        return True
    print(f"\n{'!' * 60}\n"
          f"! The first episode's reasoning was not returned.\n"
          f"{_describe(result)}\n"
          f"! The awareness grader reads the reasoning, so this arm cannot\n"
          f"! measure awareness. Pinning a different backend with\n"
          f"! --openrouter-provider may return it.\n"
          f"{'!' * 60}")
    while True:
        try:
            answer = input("Continue collecting this arm? [y/n] ").strip().lower()
        except EOFError:
            print("\nNo answer could be read; stopping.")
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            print("Stopping at the operator's request.")
            return False
