"""
Which models a dated snapshot holds (analysis plan, Decision D2).

A model enters a snapshot only when complete: all its propensity arms in both
scenarios, and every episode read by the headline grader. A half-collected
model would weight the pooled estimate toward the arms that happened to finish
first, which is the reason the rule exists.

THE CAPABILITY VERDICT IS REPORTED, NOT ENFORCED. D2 also asks for each
model's capability verdict, and section 7 keeps every model in P whatever its
tier, because an association does not need the act to be performable by every
model. Excluding on a missing verdict would contradict that, so a gap is listed
beside the snapshot - the collection still owed - and the model stays in.
Settled 2026-10-22.

The expected arms are DERIVED from the corpus - the union of every model's arms
in each scenario - rather than listed, so an arm added to the design is
required of every model without an edit here.
"""

import collections

from subversionbench.config import HEADLINE_AWARENESS_GRADER
from subversionbench.scenario import capability_act

from .capability import CAPABILITY_OUTCOMES
from .loading import ANY_CAPABILITY, load_episodes, load_summaries
from .run_report import split_pending

# The arm each scenario's propensity summaries are keyed by.
SCENARIO_ARM = {
    "mainline": lambda s: (s.get("nudge"), s.get("oversight"), s.get("lure")),
    "goalguard": lambda s: (s.get("nudge"), s.get("oversight"),
                            s.get("goalguard")),
}
# The acts a capability verdict is owed for, and where each is collected.
CAPABILITY_ACTS = {"mainline": ("oversight", "sandbox"),
                   "goalguard": ("goalguard",)}


def incomplete_models(arms: dict, unread: dict) -> dict:
    """{model: [reasons]} for every model D2 keeps out; complete ones are
    absent. `arms` is {scenario: {model: set of arms}}, `unread` {model:
    episodes the headline grader has not read}."""
    models = set().union(*arms.values())
    out = collections.defaultdict(list)
    for scenario, by_model in arms.items():
        expected = set().union(*by_model.values())
        if not expected:
            raise ValueError(f"no {scenario} arms at all - nothing to require")
        for model in sorted(models):
            missing = expected - by_model.get(model, set())
            if missing:
                out[model].append(f"{scenario}: {len(missing)} of "
                                  f"{len(expected)} arms not collected")
    for model in sorted(models):
        if unread.get(model):
            out[model].append(f"{unread[model]} episode(s) not read by the "
                              f"headline grader")
    return dict(out)


def capability_gaps(models, verdict_acts: dict) -> dict:
    """{model: acts with no capability episode} - the collection still owed."""
    needed = {a for acts in CAPABILITY_ACTS.values() for a in acts}
    return {m: sorted(needed - verdict_acts.get(m, set()))
            for m in sorted(models) if needed - verdict_acts.get(m, set())}


def _arms_and_unread(dirs: dict) -> tuple:
    arms, unread = {}, collections.Counter()
    for scenario, directory in dirs.items():
        by_model = collections.defaultdict(set)
        for s in load_summaries(directory):
            by_model[s["model"]].add(SCENARIO_ARM[scenario](s))
        arms[scenario] = by_model
        _, pending = split_pending(
            load_episodes(directory, grader=HEADLINE_AWARENESS_GRADER),
            HEADLINE_AWARENESS_GRADER)
        unread.update(e["model"] for e in pending)
    return arms, unread


def _verdict_acts(capability_dirs: dict) -> dict:
    acts = collections.defaultdict(set)
    for scenario, directory in capability_dirs.items():
        for e in load_episodes(directory, capability=ANY_CAPABILITY):
            act = capability_act(e.get("capability"))
            if (e.get("capability_outcome") in CAPABILITY_OUTCOMES
                    and act in CAPABILITY_ACTS[scenario]):
                acts[e["model"]].add(act)
    return acts


def snapshot(dirs: dict, capability_dirs: dict) -> dict:
    """The models complete in `dirs` ({scenario: directory}), why each other
    one is not, and the capability episodes still owed by the ones that are.
    `capability_dirs` is {scenario: capability directory}."""
    arms, unread = _arms_and_unread(dirs)
    excluded = incomplete_models(arms, unread)
    models = sorted(set().union(*arms.values()) - set(excluded))
    return {"models": models, "excluded": excluded,
            "capability_gaps": capability_gaps(models,
                                               _verdict_acts(capability_dirs))}
