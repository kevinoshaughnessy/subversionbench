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

`usage` may be absent entirely: OpenRouter responses carry no record in this
shape. A missing counter is reported as zero rather than guessed at.
"""


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
    return {
        "read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "written": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "uncached": int(getattr(usage, "input_tokens", 0) or 0),
        "output": int(getattr(usage, "output_tokens", 0) or 0),
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
