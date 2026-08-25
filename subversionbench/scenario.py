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
from pathlib import Path

_BUNDLE_PATH = Path(__file__).with_name("scenario.b64")

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
    """Decode the scenario bundle."""
    path = path or _BUNDLE_PATH
    raw = base64.b64decode("".join(path.read_text().split()))
    return json.loads(raw)


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


def encode_scenario(bundle: dict, path: Path = None) -> None:
    """Write a bundle back out encoded, wrapped for a readable diff."""
    path = path or _BUNDLE_PATH
    encoded = base64.b64encode(
        json.dumps(bundle, indent=1).encode()
    ).decode()
    path.write_text(
        "\n".join(encoded[i:i + 76] for i in range(0, len(encoded), 76)) + "\n"
    )


def scenario_for(oversight: bool = True, bundle: dict = None,
                 nudge: str = "strong", lure: bool = False,
                 interrogation: str = DEFAULT_INTERROGATION) -> dict:
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
    if nudge == "max":
        bundle.update(max_nudge)

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
        for key, q1 in (("followup_monitoring_questions", v["monitoring_q1"]),
                        ("followup_sandbox_questions", v["sandbox_q1"])):
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
    if lure:
        bundle.update({k: v for k, v in lure_bundle.items()
                       if k != "neighbour_file"})
        bundle["lure_neighbour_file"] = lure_bundle.get("neighbour_file")
    if oversight:
        return bundle
    for key in dropped:
        bundle.pop(key, None)
    bundle.update(overrides)
    return bundle


SCENARIO = scenario_for(True)
