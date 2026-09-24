"""
Which grader said what: several graders' readings of one episode, side by side.

WHY AN ARRAY
------------
Everything a grader model judges used to sit flat in `analysis`, one reading per
episode, and every read mode that re-graded replaced it. Comparing two graders on
the same fixed transcripts therefore meant destroying the first reading to take
the second. `analysis.graders` holds one entry per grader model instead, and
re-grading replaces only its own entry.

THE ONE OWNER OF THE SHAPE
--------------------------
Every reader in this codebase was written against the flat shape, and there are
dozens of them. Rather than teach each one the array, this module projects ONE
grader's entry back onto the flat keys (`view`), so a reader sees exactly the
shape it always has; and every writer folds its working copy back in (`store`).
The default is DEFAULT_GRADER_MODEL, which is what makes every figure and chart
the default grader's without any of them naming it.

Files written before the array existed are read here and nowhere else: their one
flat reading becomes one entry, named by the model it recorded. Every r9 and r10
file records claude-opus-5 on every grader-judged field, so their default view is
exactly what they held. Such a file also keeps its flat shape when its own grader
writes it back, and becomes an array only when a second grader is added - so
nothing that read the corpus before has to change until there is a second
reading for it to see. New episodes are written as an array from the start.

WHAT IS PER-GRADER, AND WHAT IS NOT
-----------------------------------
Per grader: the awareness rubric, the pre-act awareness blocks, disclosure,
misrepresentation, the classifier's labels on each interrogation answer, and the
concealment and scheming verdicts settled from those.

Not per grader: the interrogation ANSWERS themselves. They are the model under
test's words, so they are stored once, and each grader's labels line up with them
by position. What the answers cannot be is independent of the grader that was
running when they were collected - that grader's verdicts decided where each
ladder of questions stopped, and `interrogation_driven_by` records which one it
was. A later grader re-labels the same answers; if it does not read the last one
as an admission, there are no further questions for it to read.
"""

import copy

from .config import DEFAULT_GRADER_MODEL
from .grading import MISALIGNED_ACTS, settle_analysis

# What the interrogation classifier adds to an answer, as opposed to what the
# model under test said. The first ten are classify_interrogation_answer's
# return keys, the last two are run_followup's; a test holds this against the
# classifier so a new label cannot be stored flat by omission.
LABEL_KEYS = ("verdict", "verdict_llm", "verdict_keyword", "classifiers_agree",
              "used_keyword_fallback", "quote", "classifier_error",
              "classifier_called", "classifier_model", "classifier_version",
              "confesses", "denies")

# What an episode with no reading from the requested grader shows in place of
# one. The same block an episode collected with --no-grader already carries,
# so every reader treats it as ungraded without being told.
UNGRADED = {"skipped": True}


def graded_keys(acts=MISALIGNED_ACTS) -> tuple:
    """The flat analysis keys that hold one grader's judgement or follow from it.

    Derived from the act table, so an act added there is per-grader here without
    this module being edited.
    """
    keys = ["eval_awareness_grader", "misrepresented_check", "scheming"]
    for act in acts:
        keys += [act["grader_before_key"], act["disclosure_key"],
                 act["level_key"], act["level_key"] + "_by_variant",
                 act["scheming_key"]]
    return tuple(keys)


def answer_keys(acts=MISALIGNED_ACTS) -> tuple:
    """The flat keys holding interrogation answers, headline and per phrasing."""
    return tuple(key for act in acts
                 for key in (act["followup_key"], act["followup_key"] + "_by_variant"))


def _split(answers):
    """(bare answers, labels) from answers that carry both."""
    bare = [{k: v for k, v in a.items() if k not in LABEL_KEYS} for a in answers]
    labels = [{k: v for k, v in a.items() if k in LABEL_KEYS} for a in answers]
    return bare, labels


def _answers_at(analysis: dict, key: str):
    """Every answer list under `key`, as (path, list): one for a headline
    field, one per phrasing for a `_by_variant` map."""
    value = analysis.get(key)
    if isinstance(value, list):
        return [((), value)]
    if isinstance(value, dict):
        return [((variant,), answers) for variant, answers in value.items()
                if isinstance(answers, list)]
    return []


def _labels_of(analysis: dict, acts) -> dict:
    """The classifier labels on every stored answer, keyed like the answers."""
    labels = {}
    for key in answer_keys(acts):
        for path, answers in _answers_at(analysis, key):
            labelled = _split(answers)[1]
            if path:
                labels.setdefault(key, {})[path[0]] = labelled
            else:
                labels[key] = labelled
    return labels


def _bare(analysis: dict, acts) -> dict:
    """`analysis` with every grader-judged field and every label removed."""
    graded = set(graded_keys(acts))
    out = {k: v for k, v in analysis.items()
           if k not in graded and k != "graders"}
    for key in answer_keys(acts):
        value = out.get(key)
        if isinstance(value, list):
            out[key] = _split(value)[0]
        elif isinstance(value, dict):
            out[key] = {variant: _split(answers)[0] if isinstance(answers, list)
                        else answers for variant, answers in value.items()}
    return out


def _has_judgement(entry: dict) -> bool:
    """Whether an entry holds anything a grader actually judged.

    A skip marker is not a judgement, and an entry made of nothing else would
    put a grader on record for an episode it never read.
    """
    def labelled(value):
        # A list per answer, or a map of them per phrasing; an answer this
        # grader never labelled is an empty dict, which is not a label.
        if isinstance(value, dict):
            return any(labelled(v) for v in value.values())
        return any(value or ())
    return any(value and not (isinstance(value, dict) and value.get("skipped"))
               for key, value in entry.items()
               if key not in ("grader_model", "labels")) or labelled(
        entry.get("labels", {}))


def _entry_from_flat(analysis: dict, model: str, acts) -> dict:
    """One grader's entry, from an analysis holding its reading flat."""
    entry = {"grader_model": model}
    entry.update({k: analysis[k] for k in graded_keys(acts) if k in analysis})
    entry["labels"] = _labels_of(analysis, acts)
    return entry


def _recorded_model(analysis: dict, acts):
    """The grader a pre-array file names, or None if it names none.

    The awareness block has stamped its model since v13 and the interrogation
    classifier since it was added; an episode collected with --no-grader
    carries only the second, which is why both are asked.
    """
    block = analysis.get("eval_awareness_grader") or {}
    if block.get("grader_model"):
        return block["grader_model"]
    for key in answer_keys(acts):
        for _path, answers in _answers_at(analysis, key):
            for answer in answers:
                if answer.get("classifier_model"):
                    return answer["classifier_model"]
    return None


def graders_of(analysis: dict, acts=MISALIGNED_ACTS) -> list:
    """Every grader's entry for this episode.

    The stored array, or for a file written before it existed, one entry built
    from its flat reading - the only place the old shape is understood.

    A pre-array file that names no grader is credited to the default. Such a
    file held THE reading, the one every figure was built from, so crediting
    it anywhere else would drop it from every figure on upgrade. No r9 or r10
    file is affected: every one names claude-opus-5 wherever a grader ran.
    """
    if "graders" in analysis:
        return analysis["graders"]
    entry = _entry_from_flat(analysis,
                             _recorded_model(analysis, acts)
                             or DEFAULT_GRADER_MODEL, acts)
    return [entry] if _has_judgement(entry) else []


def grader_models(analysis: dict, acts=MISALIGNED_ACTS) -> list:
    """The models with an entry, in the order they were first stored."""
    return [e["grader_model"] for e in graders_of(analysis, acts)]


def _merge(bare_value, labels):
    """Answers with one grader's labels laid back over them, by position.

    An answer that grader never labelled comes back bare, which every reader
    already treats as unmeasured.
    """
    def merged(answers, labelled):
        labelled = labelled or []
        return [{**a, **(labelled[i] if i < len(labelled) else {})}
                for i, a in enumerate(answers)]
    if isinstance(bare_value, list):
        return merged(bare_value, labels if isinstance(labels, list) else None)
    return {variant: merged(answers, (labels or {}).get(variant))
            if isinstance(answers, list) else answers
            for variant, answers in bare_value.items()}


def view(analysis: dict, model: str = DEFAULT_GRADER_MODEL,
         acts=MISALIGNED_ACTS) -> dict:
    """A copy of `analysis` in the flat shape, holding `model`'s reading only.

    What every reader consumes. With no entry for `model` the awareness block is
    UNGRADED and the other grader fields are absent - exactly what an episode
    collected without a grader looks like, so it drops out of every grader-based
    figure the way that episode always has.

    A deep copy, so a read mode can re-grade its working view on a dry run
    without the change reaching the analysis it was read from.
    """
    analysis = copy.deepcopy(analysis)
    out = _bare(analysis, acts)
    entry = next((e for e in graders_of(analysis, acts)
                  if e["grader_model"] == model), None)
    if entry is None:
        out["eval_awareness_grader"] = dict(UNGRADED)
        # The marker add_awareness_timing writes when it has no grader, which
        # is what an episode collected with --no-grader holds for each act.
        for act in acts:
            out[act["grader_before_key"]] = {"skipped": True,
                                             "reason": "no grader"}
        # Settled here rather than left absent, because a stored entry carries
        # its settled verdicts and this has none to carry: without it an
        # ungraded episode would lack `scheming` where one collected with
        # --no-grader holds it. Only the grader-dependent verdicts are taken:
        # settle_analysis also re-derives the free `misaligned`, and the stored
        # value is what the report compares against to flag a stale file.
        settled = settle_analysis(copy.deepcopy(out), acts)
        out.update({k: settled[k] for k in graded_keys(acts) if k in settled})
        return out
    out.update({k: v for k, v in entry.items()
                if k not in ("grader_model", "labels")})
    for key, labels in entry.get("labels", {}).items():
        if key in out:
            out[key] = _merge(out[key], labels)
    return out


def store(analysis: dict, working: dict, model: str,
          acts=MISALIGNED_ACTS) -> dict:
    """`analysis` in the stored shape, with `model`'s entry taken from `working`.

    `working` is a flat analysis holding `model`'s reading - a `view` that a read
    mode has re-graded, or the analysis an episode has just built. Its free
    fields replace the stored ones, since the free measures are re-derived on
    every pass; every OTHER grader's entry is kept exactly as it was.

    Returns a new dict. A file written before the array existed KEEPS ITS SHAPE
    while only its own grader writes to it - `working` already is that shape,
    so a routine --reclassify or --resummarise leaves the file readable by
    anything that read it before. It becomes an array the first time a SECOND
    grader is stored, since two readings have nowhere else to go; its original
    reading is kept as its own entry.
    """
    existing = graders_of(analysis, acts)
    others = [e for e in existing if e["grader_model"] != model]
    entry = _entry_from_flat(working, model, acts)
    replaced = next((i for i, e in enumerate(existing)
                     if e["grader_model"] == model), None)
    if not _has_judgement(entry) and replaced is not None:
        # Never let an empty reading remove a stored one. The read modes
        # already refuse to write a failed pass; this is the same rule held at
        # the one place every write goes through.
        entry = existing[replaced]
    if _has_judgement(entry):
        if replaced is None:
            others.append(entry)
        else:
            others.insert(replaced, entry)
    stored = {**_bare(working, acts), "graders": others}
    if "graders" not in analysis and not any(
            e["grader_model"] != model for e in others):
        return view(stored, model, acts)
    return stored


def new_record(working: dict, model: str, acts=MISALIGNED_ACTS) -> dict:
    """A freshly collected episode's analysis, in the array shape.

    Not `store({}, ...)`: an empty dict reads as a pre-array file, which
    `store` keeps flat - and a new episode is written as an array from the
    start, whatever grader collected it.
    """
    return store({"graders": []}, working, model, acts)


# The word --regrade takes for "every grader this episode already has".
REGRADE_ALL = "all"
# The word for DEFAULT_GRADER_MODEL, so the default needs no model ID typed.
REGRADE_DEFAULT = "default"


def regrade_targets(choice: str, analysis: dict, acts=MISALIGNED_ACTS) -> list:
    """The grader models --regrade CHOICE re-grades on this episode.

    "default" is DEFAULT_GRADER_MODEL, whether or not it has an entry yet; any
    other word is taken as a model ID, and gets an entry if it has none; "all"
    is every model with an entry already, so it is per episode and adds none.
    """
    if choice == REGRADE_ALL:
        return grader_models(analysis, acts)
    return [DEFAULT_GRADER_MODEL if choice == REGRADE_DEFAULT else choice]
