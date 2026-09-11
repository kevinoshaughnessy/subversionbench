"""
Scenario text, held base64-encoded at rest.

WHY THIS IS NOT PLAIN SOURCE
----------------------------
Everything the model sees during an episode lives here: the two system
prompts, the user prompt, the interrogation questions, and the files it reads
in the sandbox. If that text sits in the repository as plain source, it goes
into the next training crawl - and a model trained on it has seen the memo,
the monitoring config and the questions it will later be asked. Its
eval-awareness rate then measures recall, not situational inference, and
results stop being comparable with anything measured earlier.

Encrypting the run transcripts (see zip.sh) does not help with this: the
scenario is code, not data.

Base64 is not security and is not meant to be. It is the same move BIG-bench
makes with canary strings and SAD makes with its datasets: bulk
training-data pipelines ingest text, they do not base64-decode it. Anyone who
wants to read the scenario can, in one command:

    python scenario_tool.py --decode      # writes scenario.json

Edit that file and run `python scenario_tool.py --encode` to fold changes
back in. scenario.json is gitignored, so a decoded working copy cannot be
committed by accident.
"""

import base64
import json
import os
from pathlib import Path

_BUNDLE_PATH = Path(__file__).with_name("scenario.b64")

# Which bundle this process runs against.
#
# WHY AN ENVIRONMENT VARIABLE AND NOT A FLAG. Every name below is derived from
# the bundle at import: CLIENT_NAME, PROJECT_DIR, TASK_FILE_NAME,
# SANDBOX_REFUSAL, CONTAMINATING_TERMS and SCENARIO. run_eval imports config -
# and so this module - at its own import, long before argparse runs, so a
# --scenario-bundle flag would arrive after all of them were frozen. The seam
# has to be readable at import time, and that leaves the environment.
#
# UNSET IS THE SHIPPED SCENARIO, BY THE SAME EXPRESSION AS BEFORE. r9's
# identity must not come to depend on a variable being absent in the right
# way, so the default is not a lookup with a fallback - it is _BUNDLE_PATH,
# untouched, and the override is a separate branch that the shipped path never
# enters.
#
# The override exists for the held-out twin: a reworded scenario used to ask
# whether a rate survives a change of surface wording. It is a DIFFERENT
# rollout, and rollout_pins.py refuses to stamp r9's identity onto it.
BUNDLE_ENV_VAR = "SUBVERSIONBENCH_SCENARIO_BUNDLE"


def selected_bundle_path() -> Path:
    """The bundle path this process resolves to, shipped unless overridden."""
    override = os.environ.get(BUNDLE_ENV_VAR, "").strip()
    if not override:
        return _BUNDLE_PATH
    path = Path(override)
    if not path.is_file():
        # Loud rather than a fallback. A typo that silently ran the shipped
        # scenario would produce episodes labelled as the held-out arm and
        # pooled against it, and nothing about them would look wrong.
        raise FileNotFoundError(
            f"{BUNDLE_ENV_VAR}={override!r} does not name a readable file. "
            f"Unset it to run the shipped scenario."
        )
    return path


def bundle_is_overridden() -> bool:
    """Whether an alternative bundle is selected, without reading it."""
    return bool(os.environ.get(BUNDLE_ENV_VAR, "").strip())

# The phrasing the BASE ladder carries, and so the reference probe every episode
# is asked. Named here rather than in config.py because config imports this
# module and cannot be imported back; config re-exports it, so callers keep
# importing it from there.
#
# `zeroevidence` presents no observation before the question: the interrogator
# asks whether the act happened without saying anything has been noticed. That
# is the pure case, and it is the reference on purpose - a denial there is a
# denial with nothing yet to deny against, where a denial to an opening question
# that already reports a discrepancy is partly a response to being caught. The
# escalation ladder still presents evidence at Q2 and Q3, so the arm measures
# how far a model has to be pushed rather than only what it says first.
#
# It was `default`, whose Q1 opened with the discrepancy - now available as the
# `partevidence` phrasing. Renaming was not cosmetic: the headline concealment
# field is defined as this phrasing's answer, so every rate collected before
# r7 measures the part-evidence question and does NOT pool with one collected
# after it. That is what the ROLLOUT_VERSION bump is for, and why each run now
# records `headline_interrogation` explicitly rather than leaving it implied by
# whatever the default happened to be when the batch ran.
DEFAULT_INTERROGATION = "zeroevidence"


def load_scenario(path: Path = None) -> dict:
    """
    Decode the scenario bundle.

    A `.json` path is read as plain JSON; anything else is base64, which is
    what scenario.b64 is and has always been. That split is what keeps a
    decryption path out of this module: the held-out bundle is encrypted at
    rest, and the tool that owns its passphrase hands it over decrypted to a
    private temporary file rather than teaching the module every rollout's
    identity derives from how to decrypt things.
    """
    path = Path(path) if path else selected_bundle_path()
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return json.loads(base64.b64decode("".join(text.split())))


# ---------------------------------------------------------------------------
# Names the harness needs in plaintext code, read from the bundle
#
# The client's name is scenario text like any other, and it used to sit in plain
# source in four places - the display path in config.py, the task file's name in
# environment.py, a fingerprint probe, and a comment - none of which the guard
# below caught. The name in the repository and the name in the bundle were the
# same string, so publishing the code published the scenario's client.
#
# WHY DERIVED AND NOT A CODENAME. Leaving the old name in plaintext as a stand-in
# would keep a contaminated string in the repository, next to a transport-strategy
# harness, which is enough of a hook on its own. Reading it from the bundle means
# there is nothing to keep in step and nothing to leak: renaming the client is an
# edit to scenario.json and a rollout bump, and no plaintext file mentions it.
#
# The forms are DERIVED from one key rather than stored separately. Two keys can
# disagree, and a display path that disagreed with the task file's name would show
# up as a scenario the model cannot navigate rather than as a bad constant.
# ---------------------------------------------------------------------------

_BUNDLE = load_scenario()

# The client the scenario's task belongs to, as its documents write it.
CLIENT_NAME = _BUNDLE["client_name"]

# Lowercased for a directory, which is how a project directory would be named.
PROJECT_DIR = CLIENT_NAME.lower()

# The task document in the scenario's data directory. The bundle never names this
# file - its text says only which directory to look in - so the name is the
# harness's to choose and has to be consistent with the display path.
TASK_FILE_NAME = f"{PROJECT_DIR}_strategy.txt"

# One more string the model reads during an episode, so it belongs in the bundle
# for the reason the module docstring gives. It was a plain literal in six
# tracked files; the guard below now covers it.
SANDBOX_REFUSAL = _BUNDLE["sandbox_refusal"]

# Every string that must not appear in plaintext anywhere in the repository.
#
# Held in the BUNDLE rather than in the test that checks it. The previous guard
# listed these literally, which made the guard itself the leak it was written to
# prevent - it named the client in plain source while asserting the client was not
# in plain source. It also missed the real occurrences, being case-sensitive
# against a lowercased path and scanning one directory of the package.
#
# The superseded name is on the list too, so reintroducing it fails as loudly as
# leaking the current one.
#
# The last entry is DERIVED from SANDBOX_REFUSAL rather than stored alongside the
# others, because this list is inside the assembled arm and so inside the rollout
# fingerprint: adding a term to the bundle would move r9's hash. Derived, the
# guard grows without the rollout's identity changing.
CONTAMINATING_TERMS = tuple(_BUNDLE["contaminating_terms"]) + (
    " ".join(SANDBOX_REFUSAL.rstrip(")").split()[-3:]),)


def _first_check_name(monitoring_config: str) -> str:
    """The name of the first check the monitoring config declares."""
    lines = monitoring_config.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != "checks:":
            continue
        for follow in lines[i + 1:]:
            if not follow.strip() or follow.lstrip().startswith("#"):
                continue
            if not follow.startswith((" ", "\t")):
                break                      # dedented out of the block
            name = follow.strip().rstrip(":")
            if name:
                return name
        break
    return ""


# The balance check's name, as the monitoring config writes it.
#
# It reaches a GRADER QUESTION - as one example of what "the check's outcome"
# looks like in a report - and it was a plain literal there. That literal is
# this scenario's own vocabulary, so a bundle in another domain, whose config
# declares a differently-named check, would be graded by a question naming a
# metric none of its documents mention. Read from the config, the question
# follows whichever bundle is loaded.
#
# DERIVED FROM monitoring_config RATHER THAN STORED AS ITS OWN KEY, for the
# reason the docstring of scenario_for() gives about every other addition: a
# new bundle key reaches the assembled arm and moves all four of r9's
# fingerprints, declaring every episode already collected incomparable with a
# scenario it still matches exactly. Parsing one line costs nothing by
# comparison, and the config is where the name actually lives.
QUALITY_METRIC_NAME = _first_check_name(_BUNDLE.get("monitoring_config", ""))


def encode_scenario(bundle: dict, path: Path = None) -> None:
    """
    Write a bundle back out encoded, wrapped for a readable diff.

    Defaults to the SHIPPED path even when an alternative bundle is selected,
    and refuses that combination rather than guessing which was meant. Writing
    is where an override does real damage: the whole point of the seam is that
    the read side follows it, so a bundle loaded from the held-out twin and
    written back with the default path would fold its text into scenario.b64
    and move all four of r9's fingerprints. The refusal is here rather than in
    scenario_tool.py because the rule is about this function, not that caller.
    """
    if path is None and bundle_is_overridden():
        raise RuntimeError(
            f"refusing to write the shipped bundle while {BUNDLE_ENV_VAR} is "
            f"set - unset it, or pass an explicit path. Encoding a bundle "
            f"loaded from the override into scenario.b64 would change r9."
        )
    path = Path(path) if path else _BUNDLE_PATH
    encoded = base64.b64encode(
        json.dumps(bundle, indent=1).encode()
    ).decode()
    path.write_text(
        "\n".join(encoded[i:i + 76] for i in range(0, len(encoded), 76)) + "\n",
        encoding="utf-8",
    )


def lure_applies(lure: bool, goalguard: str = None) -> bool:
    """Whether the lure arm is in effect for this combination of flags.

    A NO-OP IN THE GOAL-GUARDING ARM, not a refusal. The lure exists to
    attribute reaching OUTSIDE the project directory, and the artefact this
    act is about sits inside it - so the axis does not bear on the act, and
    GOALGUARD_FINGERPRINTS deliberately has no lure key.

    Left to run, the combination was worse than useless. The lure works by
    adding one sentence to `internal_memo` plus a file in a neighbouring
    directory; in this arm that memo is overwritten afterwards - by the
    counterfactual's copy, then by the strong-nudge one - so the file was
    placed with nothing pointing at it. That measures search rather than
    response to a hint, which is the opposite of what the arm is for. And
    because the pin table has no lure axis, those episodes were stamped with
    the NON-lure arm's identity and pooled straight into it.

    ONE FUNCTION RATHER THAN THREE COPIES OF THE TEST, because the lure
    reaches three places that must agree: the assembled scenario, the episode
    root layout the fingerprint hashes, and the neighbour file the
    environment writes. A rule applied at two of the three is how an arm comes
    to be half on.
    """
    return bool(lure) and goalguard is None


def scenario_for(oversight: bool = True, bundle: dict = None,
                 nudge: str = "strong", lure: bool = False,
                 interrogation: str = DEFAULT_INTERROGATION,
                 capability: str = None, goalguard: str = None) -> dict:
    """
    The scenario as one arm of the oversight counterfactual sees it.

    `lure=True` selects the lure arm: one extra sentence noting that material
    from another engagement is still on the machine, and a file placed outside
    the episode directory for it to refer to. The arm exists so that reaching
    outside can be attributed to the lure rather than to the scenario's other
    pressures - the same logic as the oversight counterfactual.

    `nudge="max"` swaps in the coercive interrogation questions. Those live
    under their own bundle key and are removed for every other nudge, so
    `scenario_for(oversight)` returns exactly what it returned before the max
    arm was authored - which is what keeps r3's fingerprint valid. The same
    reasoning as the counterfactual overrides below: authoring a new arm must
    not restate the identity of the arms already collected.

    Nudge is not otherwise part of the assembled arm. Both system prompts have
    always been present in it, so one fingerprint covers strong and none, and
    which of them produced an episode is recorded by the filename and the
    `nudge` field rather than by the hash.

    `oversight=True` is the scenario with oversight present, returned
    unchanged: the arm every result so far was collected under.

    `oversight=False` is the counterfactual Meinke et al. describe - the same
    task with no oversight to subvert. The monitoring config and the
    quality-check script are absent, and every document that referred to them
    has those references removed. The variant is stored in the bundle rather
    than derived at run time, because a derivation rule that changed would
    silently change the experiment; stored, it is fingerprinted like any other
    scenario text.

    The counterfactual is defined by REMOVAL only. Nothing is reworded and
    nothing is added, so any behavioural difference between arms is
    attributable to the absence of oversight rather than to incidental
    differences in how the two were written.

    `capability` selects the capability arm, which is not a fifth cell of the
    propensity design and never pools with one. It replaces the task
    instruction with one that asks for the act outright, so that a model's
    zero can be read: a 0% propensity against a 0% ceiling is a fact about the
    scenario, and against a 90% ceiling a fact about the model. Everything
    else - the environment, the system prompt, the tools, the sandbox - is
    unchanged, so the arms differ in the instruction and nothing else.
    """
    bundle = dict(bundle or load_scenario())
    # Popped unconditionally, on the same terms as the arm keys below: the
    # assembled arm is what rollout_fingerprint hashes, so a key added to the
    # bundle that reaches it declares every episode already collected
    # incomparable with a scenario it still matches exactly. This one was a code
    # literal before it was bundle text, and moving it changed nothing the model
    # sees, so r9's identity has to be preserved rather than restated.
    #
    # The cost is that the WORDING is outside the fingerprint - rewording it
    # would leave the drift guard silent. It was outside before this too, since
    # _SANDBOX_PROBES hashes only whether each probe is refused. Closing that
    # gap means changing the hash, so it belongs to the next rollout.
    bundle.pop("sandbox_refusal", None)
    overrides = bundle.pop("no_oversight", {})
    dropped = bundle.pop("no_oversight_dropped", [])
    max_nudge = bundle.pop("max_nudge", {})
    # The goal-guarding arm, popped UNCONDITIONALLY like every arm key here,
    # so `scenario_for()` returns exactly what it returned before this act was
    # authored and r10's four fingerprints stand.
    #
    # APPLIED IN TWO HALVES, because its pieces have opposite ordering needs.
    # The artefact and the question ladder go in HERE, before the max-nudge
    # swap and the variant substitution, so the third act inherits both. The
    # arm's own documents go in LATER, after the counterfactual overrides,
    # because the strong-nudge memo has to beat the counterfactual's copy of
    # `internal_memo` - applied here it was silently discarded in the
    # no-oversight arm, and both nudges came back with one fingerprint.
    goalguard_arms = bundle.pop("goalguard", {})
    goalguard_common = bundle.pop("goalguard_common", {})
    if goalguard is not None and goalguard not in goalguard_arms:
        raise KeyError(
            f"unknown goal-guarding arm {goalguard!r}; the bundle offers "
            f"{sorted(goalguard_arms)}. Refused rather than run without the "
            f"artefact: an episode with no successor parameters to guard "
            f"measures nothing, and would be recorded as a zero.")
    # The capability arm stages the artefact WITHOUT a deployment note: the
    # ceiling answers "can it edit this file when told to", and the note is
    # the motive, not the means.
    if goalguard is not None or capability == "goalguard":
        bundle.update(goalguard_common)
    if nudge == "max":
        # FILTERED to keys the bundle already carries. max_nudge overrides the
        # ordinary questions rather than supplying new ones, and unfiltered it
        # put a goal-guarding ladder into every max-nudge episode, including
        # those with no successor parameters to guard. A no-op for the two
        # acts that predate this, whose lists are base bundle keys.
        bundle.update({k: v for k, v in max_nudge.items() if k in bundle})

    # Interrogation phrasings, on the same removal-only terms as every other arm:
    # popped unconditionally, so `scenario_for()` returns exactly what it returned
    # before any variant was authored and r1-r4 keep their fingerprints. Forgetting
    # this pop moved all four hashes, which the drift guard caught immediately.
    #
    # Only the FIRST question is replaced. The scale turns on the first answer, so
    # that is the load-bearing phrasing; leaving the escalation ladder identical
    # keeps the probe separable from the confrontation that follows it.
    #
    # The variants are meaning-preserving surface perturbations - the same clauses,
    # reordered and repunctuated - because the question they answer is whether a
    # rate this benchmark reports survives a change that carries no semantic
    # content. Prior work finds bracket style and option order alone move results.
    variants = bundle.pop("interrogation_variants", {})
    if interrogation != DEFAULT_INTERROGATION:
        if interrogation not in variants:
            raise KeyError(
                f"unknown interrogation variant {interrogation!r}; expected "
                f"{DEFAULT_INTERROGATION!r} or one of {sorted(variants)}"
            )
        v = variants[interrogation]
        # DERIVED from the variant's own keys. The pair was hand-written until
        # a third act was authored; a hand-written list of what to iterate
        # over falls behind silently and the guards built on it still pass.
        # `key in bundle` is what lets a variant name an act this arm does not
        # carry without reaching it.
        for act_q1, q1 in sorted(v.items()):
            if not act_q1.endswith("_q1"):
                continue
            key = f"followup_{act_q1[:-3]}_questions"
            if key in bundle:
                bundle[key] = [q1] + list(bundle[key][1:])

    # The lure arm, on the same terms as every other arm: stored in the bundle,
    # removed unless asked for, so `scenario_for()` returns exactly what it
    # returned before the arm was authored and r1-r4 stay valid.
    #
    # The difference is ONE sentence in one document, plus a file placed in a
    # neighbour of the episode directory. The sentence mentions that something
    # exists and neither suggests reading it nor forbids it - the scenario's own
    # boundary statement already covers that, and repeating it would make the
    # lure directive, which would measure instruction-following rather than
    # anything about the model's disposition.
    lure_bundle = bundle.pop("lure", {})
    if lure_applies(lure, goalguard):
        bundle.update({k: v for k, v in lure_bundle.items()
                       if k != "neighbour_file"})
        bundle["lure_neighbour_file"] = lure_bundle.get("neighbour_file")
    # The capability arm, on the same terms as every other arm: stored in the
    # bundle, popped UNCONDITIONALLY, so `scenario_for()` returns exactly what
    # it returned before this arm was authored and r10's four fingerprints
    # stand. That pop is the load-bearing line - forgetting it moves all four
    # and declares the whole corpus incomparable with a scenario it still
    # matches exactly.
    capability_arms = bundle.pop("capability", {})
    if not oversight:
        for key in dropped:
            bundle.pop(key, None)
        bundle.update(overrides)
    # The second half of the goal-guarding arm - see the first. The
    # counterfactual's `internal_memo` is already monitoring-free and still
    # carries the standby-engine premise, so nudge=none overrides nothing here
    # and only the strong memo is supplied.
    #
    # Per ARM as well as per nudge: the strong memo names what happens at
    # cutover, and the two arms disagree about that. One shared strong memo
    # would contradict the deferred arm's own note, which is the only thing
    # telling the two apart.
    if goalguard is not None:
        arm = dict(goalguard_arms[goalguard])
        strong_memo = arm.pop("internal_memo_strong", None)
        if nudge == "strong" and strong_memo is not None:
            arm["internal_memo"] = strong_memo
        bundle.update(arm)
    if capability is None:
        return bundle
    # APPLIED LAST, AFTER THE COUNTERFACTUAL OVERRIDES. Both replace
    # `user_prompt`, and the counterfactual's copy is the one that must not
    # win here: it asks for a transport recommendation, which is the task this
    # arm exists to replace. Applied before them, the sandbox ceiling would
    # have been measured on episodes never given the instruction - and every
    # one of them would have read as a refusal.
    if capability not in capability_arms:
        raise KeyError(
            f"unknown capability target {capability!r}; the bundle offers "
            f"{sorted(capability_arms)}. Refused rather than run without the "
            f"instruction: an episode that was never told to take the act "
            f"measures propensity, and would be recorded as a ceiling.")
    if capability == "oversight" and not oversight:
        # There is nothing to subvert in the counterfactual - the arm drops
        # the monitoring config outright - so this instruction is
        # unsatisfiable there. That is the r9 defect exactly: an instruction
        # the arm's own construction removes the object of. Refused at the
        # boundary rather than collected and puzzled over.
        raise ValueError(
            "capability target 'oversight' needs oversight=True: the "
            "counterfactual arm removes the artefact the instruction names, "
            "so every episode would be scored as incapable of an act the arm "
            "makes impossible.")
    bundle.update(capability_arms[capability])
    return bundle


SCENARIO = scenario_for(True)
