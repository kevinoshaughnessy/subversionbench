"""
The scenarios a monitor reads transcripts from, one arm each.

Listed rather than discovered, for the reason model_releases.py gives: which
directory is a finished, published corpus cannot be read off its name, and the
corpora beside these (pilots, superseded collections, capability arms) are
exactly the ones a glob would sweep in. Adding a scenario's corpus here is the
whole of making it an arm.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceArm:
    """One collected scenario. `corpus` holds its propensity episodes only: a
    capability episode's act was instructed, so it is not misbehaviour."""
    name: str
    corpus: str


SOURCE_ARMS = (
    SourceArm("mainline-r10", "eval_results_r10"),
    SourceArm("goalguard-r1", "eval_results_goalguard_r1"),
)


def arm_named(name: str) -> SourceArm:
    """The arm called `name`, or a ValueError naming the ones there are."""
    for arm in SOURCE_ARMS:
        if arm.name == name:
            return arm
    raise ValueError(f"no source arm {name!r}; the arms are "
                     f"{', '.join(a.name for a in SOURCE_ARMS)}")
