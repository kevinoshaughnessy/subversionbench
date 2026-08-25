#!/usr/bin/env python3
"""
When each evaluated model was released, keyed by its OpenRouter ID.

WHY THIS IS A LIST AND family_trends.py IS NOT
----------------------------------------------
family_trends.py refuses to enumerate its families, because a hand-written list
goes stale the day the next model is collected, and goes stale SILENTLY. The
opposite reasoning applies here. A release date cannot be derived from an ID -
nothing in the string `x-ai/grok-4.5` says July 8th - so the only options are to
record it or to not have it, and a missing date announces itself the moment a
lookup returns None rather than quietly changing an answer.

So this file must be edited when a model is added. `missing_dates()` is the
guard: it names the models a corpus holds that this table does not, so the gap
is reported rather than discovered.

WHAT THE DATES ARE
------------------
The date OpenRouter lists the model as available, transcribed on 2026-08-20.
That is a ROUTE availability date, not necessarily the lab's announcement date,
and the two differ by days for some models. It is the right one for this
corpus's purposes - every model here was reached through OpenRouter, so the
listing date is when it could first have been evaluated - but it is the wrong
one for any claim about when a lab shipped something.

WHAT THIS IS FOR
----------------
Two things the version order alone cannot do:

  a calendar x-axis   - version position spaces every release equally. Four
                        grok releases spanning four months and four gemini
                        releases spanning eight look identical on a positional
                        axis, and the release dates are what distinguish them.
  a check on the order - version order is a parse of a name; the release date
                        is a fact about the world. Where they disagree, the
                        parse is what to doubt. `disagreements()` finds those,
                        and it already finds one: see kimi-k2-thinking.

Deliberately holds no rates and reads no results directory. It is a table of
dates, and joining it to a corpus is the caller's job.
"""

import sys
from datetime import date

# Every model evaluated in this corpus, with the date OpenRouter lists it.
# Grouped by provider and ordered by release within each group, so that adding a
# model puts it somewhere a reader would look for it. The grouping is a
# courtesy to whoever edits this next - nothing reads it, and
# `by_release_date()` returns the whole table in date order regardless.
RELEASE_DATES = {
    # anthropic
    "anthropic/claude-sonnet-4.5": date(2025, 9, 29),
    # Bare on purpose. This IS the model's ID for the Anthropic API, which is
    # how this corpus reached it; the `anthropic/` prefix is an OpenRouter
    # convention, and adding one here would record a route that was never used.
    # Safe for the stem fallback as long as no prefixed twin is ever added
    # beside it - which is the invariant test_no_two_keys_share_a_stem holds.
    "claude-haiku-4-5-20251001": date(2025, 10, 15),
    "anthropic/claude-sonnet-4.6": date(2026, 2, 17),
    "anthropic/claude-opus-4.8": date(2026, 5, 27),
    "anthropic/claude-sonnet-5": date(2026, 6, 30),
    "anthropic/claude-opus-5": date(2026, 7, 24),

    # deepseek
    "deepseek/deepseek-v4-pro": date(2026, 4, 24),
    "deepseek/deepseek-v4-flash": date(2026, 4, 24),
    "deepseek/deepseek-v4-flash-0731": date(2026, 7, 31),
    "deepseek/deepseek-v4-pro-0813": date(2026, 8, 12),

    # google
    "google/gemini-3-flash-preview": date(2025, 12, 17),
    # A tier of its own, not a version of gemini-flash - see QUALIFIER_TAGS in
    # family_trends.py on why `lite` defines a family rather than a stage.
    "google/gemini-3.1-flash-lite": date(2026, 5, 7),
    "google/gemini-3.5-flash": date(2026, 5, 19),
    "google/gemini-3.6-flash": date(2026, 7, 21),
    "google/gemini-3.7-flash": date(2026, 8, 13),

    # inclusionai
    "inclusionai/ling-3.0-flash": date(2026, 7, 23),

    # mistralai
    "mistralai/mistral-small-2603": date(2026, 3, 16),

    # moonshotai
    "moonshotai/kimi-k2": date(2025, 7, 11),
    "moonshotai/kimi-k2-0905": date(2025, 9, 4),
    "moonshotai/kimi-k2-thinking": date(2025, 11, 6),
    "moonshotai/kimi-k2.5": date(2026, 1, 27),
    "moonshotai/kimi-k2.6": date(2026, 4, 20),
    "moonshotai/kimi-k3": date(2026, 7, 16),

    # openai - three variants of one generation, all released together, which is
    # why they are three families here rather than three versions of one.
    "openai/gpt-5.6-luna": date(2026, 7, 9),
    "openai/gpt-5.6-terra": date(2026, 7, 9),
    "openai/gpt-5.6-sol": date(2026, 7, 9),

    # meta
    "meta-llama/llama-4-maverick": date(2025, 4, 5),
    "meta-llama/llama-4-scout": date(2025, 4, 5),
    "meta/muse-spark-1.1": date(2026, 7, 16),
    "meta/muse-spark-1.2": date(2026, 8, 6),
    "meta/muse-glimmer-30b": date(2026, 8, 9),

    # qwen
    "qwen/qwen3.5-flash-02-23": date(2026, 2, 25),
    "qwen/qwen3.6-flash": date(2026, 4, 27),
    "qwen/qwen3.7-flash": date(2026, 7, 27),
    "qwen/qwen3.8-27b": date(2026, 8, 14),

    # tencent
    "tencent/hy3": date(2026, 7, 6),

    # thinkingmachines - `inkling-small` only. The unnamed-size `inkling` is a
    # DIFFERENT model and was never evaluated here; see the deliberately
    # unmatched entry for it in the sad_oversight.py bundle.
    "thinkingmachines/inkling-small": date(2026, 7, 30),

    # x-ai
    "x-ai/grok-4.20": date(2026, 3, 31),
    "x-ai/grok-4.3": date(2026, 5, 1),
    "x-ai/grok-4.5": date(2026, 7, 8),
    "x-ai/grok-4.6": date(2026, 8, 12),

    # z-ai
    "z-ai/glm-5": date(2026, 2, 11),
    "z-ai/glm-5.1": date(2026, 4, 7),
    "z-ai/glm-5.2": date(2026, 6, 16),
    "z-ai/glm-5.3": date(2026, 8, 18),
}


def release_date(model: str):
    """
    The release date for one model ID, or None when it is not recorded.

    Falls back to matching on the part after the slash, because the same model
    is reached by two routes in this corpus - `openai/gpt-5.6-luna` natively and
    `gpt-5.6-luna` through OpenRouter - and both were released on the same day
    whatever route served them. The fallback is only taken when the stem is
    UNAMBIGUOUS across providers; a bare `kimi-k2` that matched two providers
    would return None rather than pick one.
    """
    model = model.strip()
    if model in RELEASE_DATES:
        return RELEASE_DATES[model]
    stem = model.rpartition("/")[2].lower()
    matches = {d for k, d in RELEASE_DATES.items()
               if k.rpartition("/")[2].lower() == stem}
    return matches.pop() if len(matches) == 1 else None


def by_release_date(models=None):
    """
    Model IDs in release order, oldest first.

    Ties keep the table's own order, so the three gpt-5.6 variants released on
    one day stay in the order they are written above rather than an arbitrary
    one. Models with no recorded date are dropped - `missing_dates()` is where
    they are reported.
    """
    ids = list(RELEASE_DATES) if models is None else list(models)
    dated = [(release_date(m), i, m) for i, m in enumerate(ids)
             if release_date(m) is not None]
    return [m for _, _, m in sorted(dated, key=lambda t: (t[0], t[1]))]


def missing_dates(models):
    """
    Which of these model IDs this table does not hold.

    The guard that makes a hand-maintained table safe to rely on: a corpus is
    passed in, and anything it holds that this file has not been told about is
    named. Sorted, so the output is stable enough to paste into an issue.
    """
    return sorted({m for m in models if release_date(m) is None})


def disagreements(ordered_families):
    """
    Where a family's version order contradicts its release dates.

    Takes what family_trends.group_families() returns - a mapping of family key
    to the members in version order - and reports any family whose dates do not
    ascend along that order. The version order is a parse of a naming
    convention; the dates are a fact, so a disagreement means the parse is
    wrong, or the vendor numbered a release out of sequence.

    Members with no recorded date are skipped rather than treated as undated
    zeros, which would report a disagreement that is really a missing entry.

    Returns {family: [(earlier_model, its_date, later_model, its_date), ...]},
    holding only the families that have at least one inversion.
    """
    found = {}
    for family, members in ordered_families.items():
        ids = [getattr(m, "raw", m) for m in members]
        dated = [(m, release_date(m)) for m in ids]
        dated = [(m, d) for m, d in dated if d is not None]
        inversions = [(a, da, b, db)
                      for (a, da), (b, db) in zip(dated, dated[1:]) if da > db]
        if inversions:
            found[family] = inversions
    return found


def main(argv=None):
    """Print the table in release order. Data file first, script second."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv:
        print("usage: python model_releases.py", file=sys.stderr)
        return 2
    for model in by_release_date():
        print(f"{RELEASE_DATES[model].isoformat()}  {model}")
    print(f"\n{len(RELEASE_DATES)} models, "
          f"{min(RELEASE_DATES.values()).isoformat()} to "
          f"{max(RELEASE_DATES.values()).isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
