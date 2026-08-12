"""
What names a batch, and the only code that turns that into a filename.

A batch is one arm at one moment: a model, a nudge, a reasoning effort, and which
of the counterfactual arms it was collected under. Two batches differing in any of
those are two conditions and must not pool, so the identity is what the filenames
carry - and reading it back off a filename has to be the exact inverse of writing
it, which is why both directions live here beside the tag they share.
"""

import os
import re
from dataclasses import dataclass

from .llm_client import EFFORT_LEVELS

# Marked only when oversight is ABSENT, so the episodes already collected under
# the oversight arm keep the names they have.
NO_OVERSIGHT_TAG = "nooversight"


@dataclass(frozen=True)
class BatchIdentity:
    """
    Which batch this is, passed explicitly rather than read off `args`.

    WHY NOT `args`
    --------------
    It used to be. summarise_batch built the filename it wrote from
    args.nudge/effort/oversight/lure. That is right while a batch is being
    COLLECTED, when args IS the arm, and wrong whenever one is being REBUILT,
    where the arm is whatever the run filenames say. --resummarise bridged the gap
    by assigning back onto args, and both directions of that went wrong:

      - Leaving it unset sent a rebuilt counterfactual batch to the OVERSIGHT
        arm's summary file - the single confusion the whole naming scheme exists
        to prevent. The name printed to the console was right and the file
        written was not.
      - Setting it leaked, because `args` is shared across a fan-out. The first
        fan-out processed a batch collected at effort "medium", after which every
        later model was filtered to "medium" and matched nothing: two of four
        groups silently reported "no run files", and the backfill would have been
        half done while reporting success.

    Passed explicitly, neither is expressible. `args` is what the operator typed;
    an identity is what the episodes are. Frozen, so a callee cannot reintroduce
    the problem by assigning to it.
    """
    model: str
    model_slug: str
    nudge: str
    effort: str = None
    oversight: bool = True
    lure: bool = False
    stamp: str = ""

    @property
    def stem(self) -> str:
        """The middle of every filename belonging to this batch."""
        return batch_stem(self.model_slug, self.nudge, self.effort,
                          self.oversight, self.lure)

    def filename(self, output_dir: str, prefix: str = "summary") -> str:
        """
        One of this batch's files. The stamp always comes last.

        find_run_files_by_stamp and regrade_all.sh both key off a trailing
        _<stamp>.json, so nothing may be appended after it.
        """
        stamped = f"_{self.stamp}" if self.stamp else ""
        return f"{output_dir}/{prefix}_{self.stem}{stamped}.json"

    @classmethod
    def collecting(cls, args, model_slug: str, effort, stamp: str = ""):
        """
        The arm the operator asked for - correct when a batch is being collected.

        `effort` is REQUIRED and has no default, deliberately. The level actually
        sent is resolved from the model's API generation and may differ from what
        was typed: asking a model with no effort control for `max` sends nothing,
        and the batch must not be labelled `max`. A signature defaulting it to
        args.effort would read naturally and be wrong exactly there, because None
        is a meaningful value here - "no effort was sent" - and not an absent
        argument. Passing args.effort explicitly is the caller's business.
        """
        return cls(model=args.model, model_slug=model_slug, nudge=args.nudge,
                   effort=effort, oversight=args.oversight, lure=args.lure,
                   stamp=stamp)



def batch_stem(model_slug: str, nudge: str, effort=None,
               oversight: bool = True, lure: bool = False) -> str:
    """
    The middle of every filename belonging to one batch.

    The effort level is part of a batch's identity: the same model at `low` and
    at `xhigh` are two conditions, and naming them so they differ only by
    timestamp invites their being pooled by accident. Included only when one was
    actually sent, so batches at the API default keep the names they have always
    had and results already on disk stay findable.

    The oversight arm is part of that identity for the same reason and sits
    before the effort segment, so the two compose. Marked only when oversight
    is ABSENT, so the 570 episodes already collected under the oversight arm
    keep the names they have.

    The stamp is always appended after this, never before - find_run_files_by_stamp
    and regrade_all.sh both key off a trailing _<stamp>.json.
    """
    # The interrogation phrasings are deliberately NOT part of the name. Every
    # episode is probed with the default wording plus any extras, so the default
    # measure means the same thing in every batch and they pool for it. Marking
    # the extras would split that measure across summaries and shrink its n for
    # no gain - the extras live in the run's metadata instead.
    return (f"{model_slug}_{nudge}"
            + ("" if oversight else f"_{NO_OVERSIGHT_TAG}")
            + ("_lure" if lure else "")
            + (f"_{effort}" if effort else ""))


def parse_batch_filename(path: str, nudge: str):
    """
    Read (effort, stamp, oversight) back off a run or summary filename.

    A rebuild has to name its summary after the runs it read, not after whatever
    --effort the rebuilding invocation happened to carry: otherwise
    resummarising an `xhigh` batch writes a summary claiming the default.
    Matching `_<nudge>_<level>` rather than a bare `_<level>` stops a model slug
    that happens to end in a level name from being misread.
    """
    name = os.path.basename(path)
    if name.endswith(".json"):
        name = name[:-len(".json")]

    stamp = ""
    match = re.search(r"_(\d{8}T\d{6}(?:-\d+)?)$", name)
    if match:
        stamp = match.group(1)
        name = name[:match.start()]

    # Strip the known suffixes from the right, in any order, until none match.
    #
    # Written as a loop rather than a fixed sequence because the suffixes are
    # optional and independent - a batch may carry an arm, a lure and an effort,
    # or any subset - and a fixed order breaks as soon as a new one is added
    # between two existing ones.
    #
    # The nudge guard is the subtle part: `max` is both a nudge level and an
    # effort level. Without it a `--nudge max` batch parsed as effort="max" with
    # no nudge, and batch_stem rebuilt the name with the token doubled - a second
    # summary file beside the right one, claiming an effort never requested. The
    # guard is safe because the nudge is the LAST segment left once the optional
    # suffixes are gone, so a trailing token equal to the nudge is the nudge.
    effort, lure, oversight = None, False, True
    while True:
        if name.endswith("_lure"):
            name = name[:-len("_lure")]
            lure = True
            continue
        if name.endswith(f"_{NO_OVERSIGHT_TAG}"):
            name = name[:-len(f"_{NO_OVERSIGHT_TAG}")]
            oversight = False
            continue
        if not name.endswith(f"_{nudge}"):
            for level in EFFORT_LEVELS:
                if name.endswith(f"_{level}"):
                    effort = level
                    name = name[:-len(f"_{level}")]
                    break
            else:
                break
            continue
        break

    return effort, stamp, oversight, lure
