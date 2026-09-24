"""
What one API response's usage record says, and nothing else.

THREE COPIES BEFORE THIS FILE EXISTED
-------------------------------------
`turns.cache_usage`, `grading.grader._response_cache_usage` and
`grader_ab.cost._usage_from_response` each pulled the same counters off the
same object with the same getattr-or-zero chain, two of them for the three
cache counters and the third for those plus output. One responsibility in
three places, and the wrong three: the counters are the ONLY evidence that
prompt caching engaged, because a breakpoint below the model's minimum
cacheable prefix is accepted and silently ignored. Two of this harness's
breakpoints were no-ops for a whole version and nothing but these numbers
said so.

So a provider renaming a field, or a fourth counter worth reading, had three
places to be corrected and no way to notice the two that were missed. Reading
them is one job with one reason to change - the provider's usage schema - and
it lives here.

`usage` may be absent entirely, and a missing counter is reported as zero
rather than guessed at.

TWO SHAPES, NOT ONE - and believing otherwise is what made the cache counters
useless off the native route. This file used to say "OpenRouter responses carry
no record in this shape", and read every counter with `getattr`. They do carry
one: the adapters build it with blocks._reasoning_usage, which returns a DICT,
so every getattr fell through to its default and `cache` came back
{read: 0, written: 0, uncached: 0} on each of them - not because caching
failed, but because nothing had read the numbers. `uncached: 0` for a
hundred-token prompt is the tell, and it sat in the corpus unremarked.

The two shapes also disagree on what the input total MEANS, which is the part
a rename-only fix would have got wrong:

    native Anthropic    input_tokens EXCLUDES cache reads and creations
    OpenAI-shaped       prompt_tokens / input_tokens INCLUDE cached_tokens

so `uncached` is the raw number on the first and the number minus the cached
part on the second. Mapping the names across without that subtraction would
have counted every cached token as uncached and reported that caching had not
engaged when it had.

One residual difference is left in place rather than papered over: Anthropic's
`uncached` excludes cache-creation tokens, while the OpenAI-shaped one includes
them, because those routes bill a written token as an ordinary prompt token and
do not separate it out. Aligning them would mean changing what `uncached` means
on the native route, and r9 and r10 already hold values under the old meaning.
`read` and `written` are directly comparable across routes; `uncached` is
comparable only within one.
"""


def _counter(usage, name: str) -> int:
    """One counter off either shape, zero where absent or None."""
    value = (usage.get(name) if isinstance(usage, dict)
             else getattr(usage, name, None))
    return int(value or 0)


def _names_the_cache_the_anthropic_way(usage) -> bool:
    """Which vocabulary this usage record speaks.

    Decided on whether the field EXISTS, not on whether it is set: a native
    response that used no cache still carries `cache_read_input_tokens`, as
    None, while an adapter's dict has no such key at all. Existence names the
    SHAPE; a value names the state, and only the shape decides how the input
    total has to be read.

    Measured rather than asserted, because the obvious justification for this
    is wrong: a truthiness test gives the same four numbers for a native
    response that used no cache. The subtraction is by zero there, and the
    OpenAI branch's fallback chain lands on `input_tokens` and `output_tokens`
    anyway. So this is a clarity choice and not a correctness one, and saying
    otherwise would be a comment claiming to prevent a defect it does not.
    """
    names = ("cache_read_input_tokens", "cache_creation_input_tokens")
    if isinstance(usage, dict):
        return any(name in usage for name in names)
    return any(hasattr(usage, name) for name in names)


def token_counts(response) -> dict:
    """
    Every token counter one response carries, zero where absent.

    `output` is the number the grader A/B experiment exists to stop guessing
    at. A model that cannot disable thinking bills its reasoning as part of
    output_tokens on Anthropic's own API - there is no separate field for it -
    so capturing this one number is the actual measurement, and a price table
    only turns it into dollars.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"read": 0, "written": 0, "uncached": 0, "output": 0}
    if _names_the_cache_the_anthropic_way(usage):
        return {
            "read": _counter(usage, "cache_read_input_tokens"),
            "written": _counter(usage, "cache_creation_input_tokens"),
            # Raw, because this route reports it already net of the cache.
            "uncached": _counter(usage, "input_tokens"),
            "output": _counter(usage, "output_tokens"),
        }
    read = _counter(usage, "cached_tokens")
    # prompt_tokens on chat completions, input_tokens on the Responses API,
    # and both are the total INCLUDING the cached part - see the module
    # docstring.
    input_total = (_counter(usage, "prompt_tokens")
                   or _counter(usage, "input_tokens"))
    return {
        "read": read,
        "written": _counter(usage, "cache_write_tokens"),
        # Floored at zero so a provider reporting more cached tokens than
        # prompt tokens cannot push a negative into the sums these feed.
        "uncached": max(input_total - read, 0),
        "output": (_counter(usage, "completion_tokens")
                   or _counter(usage, "output_tokens")),
    }


def cache_usage(response) -> dict:
    """
    The three cache counters, without the output count.

    A narrower view rather than a second reader, and the narrowness is load
    bearing: this dict is stored on every episode as its `cache` field and
    summed by the quality facts, so a fourth key here would change what a
    saved run carries. `token_counts` is for a caller that wants to price a
    call; this is for one that wants to know whether caching engaged.
    """
    return {key: value for key, value in token_counts(response).items()
            if key != "output"}
