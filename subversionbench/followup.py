"""What happens after the loop ends: the interrogation, and when awareness
was verbalised relative to the act.

Separate from the loop for the reason episode.py's docstring gives: the
interrogation starts from the conversation as the episode LEFT it, so several
phrasings can be put to the same episode without any of them seeing another's
question. That is also what lets --reinterrogate add a phrasing to episodes
already collected, months later, without re-running a rollout.
"""

from . import grading as grading_api
from .api_errors import api_error_message, warn_usage_limit_once
from .config import DEFAULT_GRADER_MODEL, DEFAULT_INTERROGATION
from .grading import (MISALIGNED_ACTS, awareness_timing,
                      first_awareness_position, questions_for,
                      report_grader_failure)
from .redaction import redact_paths
from .turns import replayable_content


def interrogate_acts(analysis: dict, transcript: list, probe: dict, *,
                     grader_model: str, nudge: str, interrogations: tuple,
                     ended_by: str) -> None:
    """
    Ask the model about each misaligned act it took, and record what it said.

    `probe` is what run_followup needs to reach the model under test - the
    conversation as the episode left it, the client, and the request settings.
    Grouped rather than passed one at a time because none of the six is read
    here: they exist only to be handed straight through, and threading them
    individually made this function's signature a copy of another function's.

    Concealment is what separates scheming from plain misalignment, so every act
    gets its own probe. They share one conversation: a single investigator asking
    about two things, rather than two models in two disconnected worlds.

    Writes the disclosure, misrepresentation and follow-up fields onto
    `analysis` in place. Nothing is settled here - `settle_analysis` in the
    caller does that, after this has supplied the evidence it needs.
    """
    # An episode that ran out of turns never produced a closing report - the
    # model was cut off mid-task - so there is nothing to judge disclosure
    # against. Scoring the last thing it happened to say ("Trying even smaller
    # appends.") as a non-disclosure would be reading a verdict out of noise.
    has_report = ended_by != "turn_cap"

    if analysis.get("oversight_tampered") and has_report:
        # Did the closing report claim the check passed, without saying the
        # agent is why it passed? Stronger than omission.
        analysis["misrepresented_check"] = grading_api.detect_misrepresentation(
            transcript, model=grader_model
        )

    for act in MISALIGNED_ACTS:
        # None means the act was not available in this arm - there was no
        # oversight to subvert - so there is nothing to interrogate about.
        # Asking anyway would put the idea in front of a model the scenario
        # deliberately never mentioned it to.
        if not analysis.get(act["key"]):
            continue

        # Did it own up in its closing report, before anyone asked? That is
        # the covert limb of the definition and needs no interrogation.
        analysis[act["disclosure_key"]] = (
            grading_api.detect_disclosure(transcript, act["description"],
                              model=grader_model)
            if has_report else
            {"disclosed": None, "quote": "",
             "error": "episode hit the turn cap; no closing report"}
        )

        # PAIRED, not one phrasing per batch. Each probe starts from the episode
        # as it ended - run_followup copies the message list rather than extending
        # it - so a second wording cannot see the first and there is no order
        # effect to control for. That is the same property that already lets the
        # two ACTS be interrogated independently from one episode.
        #
        # Paired is both cheaper and better powered. The agent rollout is paid for
        # once: an interrogation is about 16% of an episode's wall clock, against
        # 100% for a second batch. And because both probes share everything about
        # the episode, between-episode variance drops out of the comparison, which
        # matters when the rate being compared is currently zero.
        by_variant = {}
        for variant in interrogations:
            if len(interrogations) > 1:
                print(f"\n*** {act['banner']} - interrogation [{variant}] ***\n")
            else:
                print(f"\n*** {act['banner']} - Running follow-up "
                      f"interrogation ***\n")
            by_variant[variant] = run_followup(
                probe["system_prompt"], probe["messages"], probe["model"],
                probe["client"], act,
                questions=questions_for(act, nudge, variant),
                classifier_model=grader_model,
                max_tokens=probe["max_tokens"],
                reasoning_kwargs=probe["reasoning_kwargs"],
                env_dir=probe["env_dir"],
            )

        # The headline field holds the DEFAULT phrasing and nothing else, so every
        # rate over the episodes already collected keeps its meaning and the two
        # can be pooled. The extras sit beside it.
        analysis[act["followup_key"]] = by_variant[DEFAULT_INTERROGATION]
        if len(by_variant) > 1:
            analysis[act["followup_key"] + "_by_variant"] = by_variant


def run_followup(system_prompt, messages, model, client, act,
                 classifier_model=DEFAULT_GRADER_MODEL,
                 max_tokens=2048, reasoning_kwargs=None, env_dir=None,
                 questions=None):
    """
    Interrogate the model about one misaligned act it took.

    Escalating questions, stopping as soon as it admits the act - there is
    nothing left to establish once it has. Each answer is classified as an
    admission, a denial, or neither; see the notes in config.py on why the
    third category exists rather than treating any non-admission as a lie.

    Each interrogation starts from the episode as it ended, NOT from a
    previous interrogation. Chaining them would make the second probe
    conditional on the first - a model that had just admitted one act is
    plausibly likelier to admit the next - which is an order effect confounding
    two rates that get reported separately. Independent probes cost one extra
    prompt prefix and remove it.
    """
    create_kwargs = dict(
        model=model, max_tokens=max_tokens, system=system_prompt,
        **(reasoning_kwargs or {}),
    )

    responses = []
    current_messages = list(messages)
    label = f"FOLLOWUP {act['topic']}".strip()

    for q in (questions if questions is not None else act["questions"]):
        print(f"[{label} Q] {q}")
        current_messages.append({"role": "user", "content": q})

        response = client.messages.create(messages=current_messages, **create_kwargs)

        # content[0] isn't necessarily the answer - a thinking block (or,
        # for OpenRouter, the reasoning capture) can precede it.
        text_block = next((b for b in response.content if b.type == "text"), None)
        answer = redact_paths(text_block.text if text_block else "", env_dir)

        # One retry when the model returns no text. Scoring is safe without it
        # - an empty reply is recorded as NO_ANSWER and excluded rather than
        # read as stonewalling - but an excluded answer is still a question
        # that went unmeasured, and on google/gemini-3.5-flash that was 22% of
        # them. Ask again before giving up on the measurement.
        retried = False
        if not answer.strip():
            retried = True
            print(f"[{label} A] (no text returned, "
                  f"stop_reason={getattr(response, 'stop_reason', None)}, "
                  f"blocks={[b.type for b in response.content]}; asking once more)")
            response = client.messages.create(messages=current_messages,
                                              **create_kwargs)
            text_block = next((b for b in response.content
                               if b.type == "text"), None)
            answer = redact_paths(text_block.text if text_block else "", env_dir)

        # What the model actually returned, recorded whether or not it answered.
        #
        # Without this an empty answer is unexplainable after the fact: nothing
        # distinguished reasoning that ran out of budget from a tool call
        # offered instead of an answer from a refusal. 42 saved answers were
        # empty and the cause had to be reconstructed by elimination - the
        # adapter's no-visible-output diagnostic appeared in none of them, which
        # ruled out budget exhaustion and left "returned a tool_use block and no
        # text", i.e. the model tried to act rather than answer. `block_types`
        # would have said so directly.
        response_meta = {
            "stop_reason": getattr(response, "stop_reason", None),
            "block_types": [b.type for b in response.content],
            "retried_after_empty": retried,
        }
        print(f"[{label} A] {answer[:400]}\n")
        # Same constraint as the main loop: an empty text block coming back
        # here would 400 the *next* question in the interrogation.
        current_messages.append({
            "role": "assistant",
            "content": replayable_content(response.content),
        })

        labelled = grading_api.classify_interrogation_answer(
            answer, act["description"],
            act["admission"], act["denial"], act["contrition"],
            model=classifier_model,
        )
        verdict = labelled["verdict"]
        confesses = verdict == "admitted"

        if labelled["classifiers_agree"] is False:
            print(f"  [classifier] LLM={labelled['verdict_llm']} "
                  f"keyword={labelled['verdict_keyword']} - using LLM")
        if labelled["used_keyword_fallback"]:
            # The provider's own sentence, not the SDK's repr of the envelope
            # around it. Truncating the repr cut a spend-cap message to
            # "You have " and made an account limit look like a harness bug.
            error = labelled["classifier_error"]
            warn_usage_limit_once(error, "interrogation classifier")
            print(f"  [classifier] LLM classification failed "
                  f"({api_error_message(error, limit=160)}); "
                  f"fell back to keyword verdict {verdict!r}")
        print(f"  [verdict] {verdict}")

        responses.append({
            "question": q,
            "answer": answer,
            "confesses": confesses,
            "denies": verdict == "denied",
            **labelled,
            **response_meta,
        })

        if confesses:
            print(f"[{label}] Model admitted the act. Stopping interrogation.")
            break

    return responses


def add_awareness_timing(analysis: dict, transcript: list, grader_model=None):
    """
    Record when awareness was verbalised relative to each misaligned act.

    Two measures, for the same reason the episode-level awareness has two: the
    keyword ordering is exact and free, and the keyword detector under-detects
    badly - 11 of 69 acts in the pilot data had any indicator phrase at all.
    So where a grader is available the awareness rubric is also run over the
    transcript *as it stood before the act*, which is the only way to ask the
    grader an ordered question at all: it is handed one blob of transcript and
    has no notion of when anything was said.

    Runs the rubric once per distinct act position - the two acts land on the
    same prefix often enough to be worth not paying for twice, and only 3 of
    300 pilot episodes committed both acts.
    """
    aware_index, aware_turn = first_awareness_position(transcript)
    # Episode-level and act-independent, so a later analysis can condition on
    # "aware by turn N" without reference to whether an act happened at all -
    # see the note on selection bias in README.md.
    analysis["first_awareness_index"] = aware_index
    analysis["first_awareness_turn"] = aware_turn

    graded_prefixes = {}
    for act in MISALIGNED_ACTS:
        timing = awareness_timing(transcript, analysis, act)
        analysis[act["timing_key"]] = timing

        act_index = timing["act_index"]
        if grader_model is None or act_index is None:
            # Never replace a real grader reading with a skip marker.
            # --reclassify runs with no grader by design, and overwriting here
            # destroyed pre-act awareness results that had cost API calls -
            # a whole 100-run batch of them - leaving the ordering to fall back
            # to the keyword measure, which under-detects badly.
            existing = analysis.get(act["grader_before_key"]) or {}
            if (not existing.get("skipped")
                    and not existing.get("grading_failed")
                    and existing.get("eval_aware") is not None):
                continue
            analysis[act["grader_before_key"]] = {
                "skipped": True,
                "reason": ("no grader" if grader_model is None
                           else f"act not located: {timing['timing']}"),
            }
            continue

        if act_index not in graded_prefixes:
            print(f"\n--- Running awareness grader on the transcript before "
                  f"the {act['name']} act ---")
            graded_prefixes[act_index] = grading_api.detect_eval_awareness_grader(
                transcript[:act_index], model=grader_model
            )
            report_grader_failure(graded_prefixes[act_index],
                                  what=f"pre-{act['name']}-act awareness grader")
        result = dict(graded_prefixes[act_index])
        result["act_index"] = act_index
        result["act_turn"] = timing["act_turn"]
        analysis[act["grader_before_key"]] = result

        print(f"[AWARENESS TIMING] {act['name']}: keywords={timing['timing']}, "
              f"grader_before_act={result.get('eval_aware')}")
