"""
What names a batch, and the only code that turns that into a filename.

A batch is one arm at one moment: a model, a nudge, a reasoning effort, and which
of the counterfactual arms it was collected under. Two batches differing in any of
those are two conditions and must not pool, so the identity is what the filenames
carry - and reading it back off a filename has to be the exact inverse of writing
it, which is why both directions live here beside the tag they share.
"""

import datetime
import glob
import json
import os
import re
from dataclasses import dataclass

from .llm_client import EFFORT_LEVELS

# Marked only when oversight is ABSENT, so the episodes already collected under
# the oversight arm keep the names they have.
NO_OVERSIGHT_TAG = "nooversight"

# The capability arm's mark, and the first line of defence keeping it out of
# every propensity rate. A capability episode pooled into a misalignment rate
# would inflate it catastrophically - the act was INSTRUCTED there - so the
# arm is marked in the filename, stamped with its own rollout fingerprint, and
# dropped by both report loaders. Three independent defences, because the
# consequence of one failing silently is a published rate that is wrong in the
# direction nobody checks.
#
# Hyphenated rather than underscored inside the token. The suffix stripper
# below peels `_`-separated segments, and `_capability_sandbox` would present
# it with two segments to peel where one has meaning.
CAPABILITY_TAG = "capability"


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
    # None on every propensity batch, which is all of them until one is
    # collected under --capability. Part of the identity rather than a
    # separate flag because a capability batch and a propensity batch of the
    # same model, nudge and arm are two conditions whose summaries must not
    # land on the same filename.
    capability: str = None

    @property
    def stem(self) -> str:
        """The middle of every filename belonging to this batch."""
        return batch_stem(self.model_slug, self.nudge, self.effort,
                          self.oversight, self.lure, self.capability)

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
                   stamp=stamp, capability=getattr(args, "capability", None))



@dataclass(frozen=True)
class BatchSelection:
    """
    Which batch a read mode was pointed at, passed rather than read off `args`.

    WHY THIS EXISTS SEPARATELY FROM BatchIdentity
    ---------------------------------------------
    BatchIdentity is what the EPISODES are - the full arm, recovered from run
    filenames when a batch is rebuilt, and written back into the names of
    everything derived from it. A selection is narrower and earlier: the (model,
    nudge) pair a read mode was ASKED to operate on, before any file has been
    read.

    They are not the same question and one cannot stand in for the other. A read
    mode needs the selection to find its run files at all; the identity of what
    it then found is whatever those filenames say, which for a rebuild is not
    what the operator typed.

    WHY NOT `args`
    --------------
    Because `--model all` fans out, running the same mode once per (model, nudge)
    in a directory. There is exactly one `args`, shared by every iteration, so
    varying the arm meant assigning onto it - and that leaked. The arm fields
    stopped leaking when BatchIdentity was introduced; model and nudge went on
    doing so, harmless only because the loop rewrote both every time round, and
    leaving `args` holding the last batch's pair afterwards rather than what was
    typed.

    Passing the selection makes the leak unexpressible rather than merely absent,
    and makes each read mode's signature say what selects its work. Frozen, so a
    callee cannot reintroduce the problem by assigning to it.

    `model_slug` is derived rather than carried. It was a second parameter beside
    the model on ten functions, each caller doing its own `replace("/", "_")` -
    four such derivations in source - which is four chances to spell it
    differently for a model whose name contains a slash.
    """
    model: str
    nudge: str

    @property
    def model_slug(self) -> str:
        """The model as it appears in a filename.

        OpenRouter model ids are `provider/model`, and the slash would otherwise
        be read as a path separator.
        """
        return self.model.replace("/", "_")

    @classmethod
    def typed(cls, args):
        """What the operator asked for - correct for a single named batch.

        Not for a fan out, where the typed value is the literal `all` and each
        iteration's pair comes from the directory instead.
        """
        return cls(model=args.model, nudge=args.nudge)


def batch_stem(model_slug: str, nudge: str, effort=None,
               oversight: bool = True, lure: bool = False,
               capability: str = None) -> str:
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
    # The capability mark sits FIRST among the optional suffixes, so that a
    # directory listing sorts a model's capability batches away from its
    # propensity ones rather than interleaving them by effort.
    return (f"{model_slug}_{nudge}"
            + (f"_{CAPABILITY_TAG}-{capability}" if capability else "")
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
    effort, lure, oversight, capability = None, False, True, None
    while True:
        if name.endswith("_lure"):
            name = name[:-len("_lure")]
            lure = True
            continue
        if name.endswith(f"_{NO_OVERSIGHT_TAG}"):
            name = name[:-len(f"_{NO_OVERSIGHT_TAG}")]
            oversight = False
            continue
        # Matched by prefix on the segment, not against a list of known
        # targets: a target added to the bundle later must be readable off a
        # filename written today, and a parser that fell back to None for an
        # unrecognised one would silently return a capability batch as a
        # propensity batch - which is the single reading this tag exists to
        # prevent.
        marked = re.search(rf"_{CAPABILITY_TAG}-([^_]+)$", name)
        if marked:
            capability = marked.group(1)
            name = name[:marked.start()]
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

    return effort, stamp, oversight, lure, capability

# =========================================================================
# Finding a batch on disk
# =========================================================================
#
# The inverse of the naming above, and here for the same reason parse_batch_filename
# is: a stamp that is written one way and searched for another finds nothing, and
# finds it silently.

def find_run_files_by_stamp(output_dir: str, stamp: str) -> list:
    """Every run file from one batch, whatever model or nudge it used."""
    return sorted(glob.glob(os.path.join(output_dir, f"run_*_{stamp}.json")))


def unique_batch_stamp(output_dir: str) -> str:
    """
    A filename suffix identifying this batch, unique within output_dir.

    One stamp is used for the whole batch, so re-running the same model and
    nudge never overwrites earlier results and each run file sorts next to
    the summary it belongs to. Compact and colon-free: sorts chronologically
    as text and stays a legal filename on every platform.

    Second resolution alone isn't enough - two batches started in the same
    second would collide and the later one would silently overwrite the
    earlier, which is the exact thing the stamp exists to prevent. Unlikely
    for a real batch, easy to hit with `--runs 1 --no-grader`. So take the
    first stamp not already present on disk.
    """
    base = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")

    stamp = base
    attempt = 1
    while glob.glob(os.path.join(output_dir, f"*_{stamp}.json")):
        attempt += 1
        stamp = f"{base}-{attempt}"

    return stamp

# The wildcard a read mode passes to work on every batch in a directory rather
# than one. A sentinel rather than None because it is a value the operator types.
ALL = "all"


def discover_batches(output_dir: str, model: str = ALL,
                     nudge: str = ALL) -> list:
    """
    The (model, nudge) pairs actually present in a results directory.

    Read from each run file's own `model` and `nudge` fields rather than parsed
    out of the filename. The filename is ambiguous - a model slug can itself
    contain underscores, and the arm suffixes sit between the slug and the stamp
    - and getting it wrong here would silently skip batches, which is worse than
    being slow. 860 files parse in a few seconds.

    Only pairs that EXIST are returned, so fanning out cannot produce a run of
    "no run files for ..." errors for combinations that were never collected.

    `model` and `nudge` each act as a filter when given concretely and as a
    wildcard when "all", so --model all --nudge strong is one arm across every
    model, and --model all --nudge all is a whole directory.
    """
    pairs = set()
    for path in sorted(glob.glob(os.path.join(output_dir, "run_*.json"))):
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue                    # a truncated run file is not a batch
        m, n = data.get("model"), data.get("nudge")
        if not m or not n:
            continue
        if model != ALL and m != model:
            continue
        if nudge != ALL and n != nudge:
            continue
        pairs.add((m, n))
    return sorted(pairs)


def find_run_files(output_dir: str, model_slug: str, nudge: str,
                   batch_stamp: str = None, effort: str = None,
                   oversight: bool = None) -> list:
    """
    Existing run files for one model and nudge, oldest batch first.

    Several patterns are matched because the filename has grown twice. Runs
    saved before batch stamps existed are named run_<i>_<model>_<nudge>.json
    with nothing after the nudge, and runs from a batch that requested an
    --effort carry it between the nudge and the stamp. All of them are equally
    gradeable, so leaving any shape unmatched would silently skip whole batches
    - which is how a results directory ends up half re-graded with nothing to
    show that it is.

    `effort` narrows to one level. Left as None, every level matches, so a
    caller that does not care (--grade-existing, --resummarise) sees the
    batches regardless of what they were run at.
    """
    # Glob broadly, then filter on the identity parsed back out of each name.
    # Pattern-matching the arm directly does not work: the trailing wildcard
    # that stands in for the stamp also swallows a `_nooversight` segment, so
    # a filter for the oversight arm silently returned the counterfactual's
    # episodes too.
    prefix = f"run_*_{model_slug}_{nudge}"
    if batch_stamp:
        # Matched as a literal, not parsed back: --batch-stamp takes any
        # string, while parse_batch_filename only recognises a datetime-shaped
        # one, so filtering on the parsed value drops every other shape.
        found = set(glob.glob(
            os.path.join(output_dir, f"{prefix}*_{batch_stamp}.json")))
    else:
        found = set(glob.glob(os.path.join(output_dir, f"{prefix}_*.json")))
        found.update(glob.glob(os.path.join(output_dir, f"{prefix}.json")))

    # The slug must be the WHOLE segment between the run index and the nudge.
    #
    # The glob above cannot express that: the `*` standing in for the run index
    # matches across underscores, so `run_*_gpt-5.4_strong` also matched
    # `run_10_openai_gpt-5.4_strong` with the wildcard eating `10_openai`. A
    # shorter slug therefore swept in the files of any model whose name it is a
    # suffix of, and both spellings exist in this corpus.
    #
    # Two consequences, both live before this filter. Summarising `gpt-5.4`
    # covered 20 files rather than 10, which is where the primary-arm denominator
    # of 630 came from when the truth was 610. And fanning a paid regrade out over
    # a directory would have graded those 20 files twice.
    #
    # Third instance of the bare-substring class in this repository, after the
    # blocked-command matcher and the awareness keyword list. Same fix: require
    # the delimiters.
    delimited = re.compile(
        rf"^run_\d+_{re.escape(model_slug)}_{re.escape(nudge)}(_.*)?\.json$")

    keep = []
    for path in found:
        if not delimited.match(os.path.basename(path)):
            continue
        got_effort, _, got_oversight, _got_lure, _got_cap = parse_batch_filename(
            path, nudge)
        if effort is not None and got_effort != effort:
            continue
        if oversight is not None and got_oversight != oversight:
            continue
        keep.append(path)

    return sorted(keep)
