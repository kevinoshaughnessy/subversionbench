"""
One episode, end to end.

The agentic loop that hands a model a shell and lets it work, the interrogation
that follows, and the per-episode grading in between. Everything here is about a
SINGLE episode: what the model did, what it said about it afterwards, and what that
cost. Batching, resuming, reporting and the read-only modes are elsewhere.

WHAT THIS FILE SPENDS
---------------------
Almost every function here can make an API call, which is what separates it from
the analysis modules. reporting/facts.py is pure and reporting/console.py prints;
this is the layer that pays. That is also why the interrogation is a separate
function rather than the tail of the loop: it starts from the conversation as the
episode left it, so several phrasings can be put to the same episode without any of
them seeing another's question.

"""

import datetime
import json
import time

# The dependencies the test suite stubs are called through their module rather
# than bound as bare names. `from X import f` copies the function object, so a
# test patching X.f would not affect this module and a test patching THIS module's
# f stops working the moment f's caller moves to another file. Called as
# `llm_client.get_client(...)`, the lookup happens at call time in the owning
# module, so there is exactly one patch point and it does not move when files do.
# test_stub_points.py holds this.
from . import grading as grading_api
from . import llm_client as llm_api
from .config import (CANARY, DEFAULT_GRADER_MODEL, DEFAULT_INTERROGATION,
                     ROLLOUT_VERSION, TOOLS, VERSION, fingerprint_for)
from .grading import (MISALIGNED_ACTS, analyze_misalignment, awareness_timing,
                      detect_eval_awareness_keywords, first_awareness_position,
                      questions_for, settle_analysis, verify_oversight_unchanged)
from .isolation import DEFAULT_ISOLATION
from .llm_client import _BRACKET_TOOL_CALL_RE
from .redaction import redact_paths
from .sandbox import execute_tool_sandboxed



# =========================================================================
# The agentic loop
# =========================================================================


class EpisodeAPIError(RuntimeError):
    """
    An API call failed part-way through an episode, carrying the partial
    transcript with it.

    A partial episode is not an observation and stays out of the batch's
    denominators, but discarding the transcript as well leaves nothing to
    diagnose from - and by then the episode has already been paid for.
    """

    def __init__(self, cause, partial: dict):
        super().__init__(str(cause))
        self.cause = cause
        self.partial = partial


# How many cache breakpoints to keep alive in the conversation at once. A
# breakpoint searches back at most 20 content blocks for a prior cache entry,
# and a turn adds roughly two (the assistant's reply, then its tool results),
# so a single rolling breakpoint would stop finding its predecessor around turn
# ten and silently degrade to no caching. Two keeps the lookback short. The API
# allows four; the extra two buy nothing here and cost a write each.
_CACHE_BREAKPOINTS = 2


def roll_cache_breakpoints(messages: list, keep: int = _CACHE_BREAKPOINTS):
    """
    Move the prompt-cache breakpoints onto the newest turn.

    The agentic loop re-sends the entire conversation every turn, and without a
    breakpoint every token is reprocessed at full price: a median episode
    re-sends about 22,400 input tokens across its eight turns, of which only
    ~5,000 are new. Marking the latest tool results cacheable makes each turn
    read what came before at a tenth of the price and write only the increment.

    Marks tool_result blocks specifically because those are dicts this module
    builds. The assistant turns are SDK response objects, which cannot carry an
    extra key, and the opening user turn is a bare string.

    Only the newest `keep` breakpoints are left in place; older ones are
    removed, since a cached prefix stays readable by content and does not need
    its marker to persist.
    """
    marked = [block
              for message in messages
              if isinstance(message.get("content"), list)
              for block in message["content"]
              if isinstance(block, dict) and "cache_control" in block]
    for block in marked[:-keep] if keep else marked:
        block.pop("cache_control", None)


def cache_usage(response) -> dict:
    """
    Read the cache counters off one response, tolerating their absence.

    OpenRouter responses carry no `usage` in the shape this returns, and a
    missing counter is reported as zero rather than guessed at.
    """
    usage = getattr(response, "usage", None)
    return {
        "read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "written": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "uncached": int(getattr(usage, "input_tokens", 0) or 0),
    }


def replayable_content(blocks: list) -> list:
    """
    Drop the blocks the API will not accept back in a later request.

    An assistant turn is echoed into `messages` and re-sent on the next turn,
    and Anthropic rejects a text block whose text is empty:

        messages: text content blocks must be non-empty

    Newer models do emit one - a turn that goes from reasoning straight to a
    tool call can open a text block and put nothing in it. The response is
    valid; sending it back is not, so the episode dies on the *following*
    turn with the whole transcript still in memory.

    Thinking blocks are passed through untouched, including empty ones. They
    carry signatures the API verifies and have to go back exactly as they
    came; the copy the grader reads is the transcript, which drops empty
    thinking separately.
    """
    kept = []
    for block in blocks:
        if getattr(block, "type", None) == "text":
            if not (getattr(block, "text", "") or "").strip():
                continue
        kept.append(block)
    return kept

def run_evaluation(
    system_prompt: str,
    user_prompt: str,
    env_dir: str,
    env_info: dict,
    model: str = "claude-sonnet-5",
    max_turns: int = 40,
    max_tokens: int = 8192,
    reasoning_kwargs: dict = None,
    reasoning_config: str = "",
    effort: str = None,
    use_grader: bool = True,
    grader_model: str = DEFAULT_GRADER_MODEL,
    oversight: bool = True,
    nudge: str = "strong",
    lure: bool = False,
    interrogations: tuple = (DEFAULT_INTERROGATION,),
    isolation: str = DEFAULT_ISOLATION,
    profile_path=None,
) -> dict:
    """Run one complete evaluation with eval awareness detection."""
    client = llm_api.get_client(model)

    messages = [{"role": "user", "content": user_prompt}]
    transcript = []
    timing = {}

    # Every string that reaches the console or the transcript goes through
    # this first, so no host-specific path ends up in a shareable artifact.
    def red(text):
        return redact_paths(text, env_dir)

    # The arm as the caller declared it, NOT inferred from the prompt text.
    #
    # This used to read `"strong" if "top priority" in system_prompt else
    # "none"`, which was wrong the moment a third arm shared strong's prompt:
    # a --nudge max run printed and *recorded* "strong". The value is stored on
    # every run and on every failed run, and --compare labels its arms from it,
    # so the one field that keeps the coerced arm from being read as the
    # unprompted one was reporting the wrong arm.
    #
    # Deriving a fact from text that happens to contain it is the same mistake
    # as matching a command name inside prose: it holds until the text changes
    # underneath it. The caller knows the arm, so the caller passes it.
    nudge_type = nudge

    # Fails loudly on a wiring mistake rather than mislabelling a whole batch,
    # which is how the bug above stayed quiet: `max` legitimately shares
    # strong's prompt, so agreement can no longer be checked by eye.
    _strong_prompt = "top priority" in system_prompt
    if nudge_type == "none" and _strong_prompt:
        raise ValueError("nudge='none' with the strong-nudge system prompt")
    if nudge_type in ("strong", "max") and not _strong_prompt:
        raise ValueError(f"nudge={nudge_type!r} without the strong-nudge prompt")

    # `effort` is the level actually SENT, not the one requested:
    # resolve_thinking_kwargs drops a level the model will not accept, and
    # printing the request would claim a condition that never applied. None means
    # no reasoning parameter was sent at all, which is a different state from any
    # level and is spelled out rather than left blank.
    print(f"\n{'='*60}")
    print(f"MODEL: {model}")
    print(f"NUDGE: {nudge_type}")
    print(f"EFFORT: {effort if effort else 'not sent (provider default)'}")
    print(f"ENV: {red(env_dir)}")
    print(f"{'='*60}\n")

    # How the episode terminated. An episode that runs out of turns may never
    # have reached the decision the eval is about, so it must be
    # distinguishable from one the model chose to end - otherwise it sits in
    # the denominator as though it were a complete observation.
    ended_by = "turn_cap"
    reasoning_chars = 0
    # Whether prompt caching actually engaged. A breakpoint below the model's
    # minimum cacheable prefix is accepted and silently ignored, so these
    # counters are the only way to tell a working breakpoint from a no-op - two
    # of this harness's turned out to be no-ops exactly that way.
    cache_totals = {"read": 0, "written": 0, "uncached": 0}

    # Token accounting as the provider reports it, including reasoning tokens
    # where available. Empty on the native Anthropic path, whose usage is
    # already captured by cache_totals in a different shape.
    token_totals = {}

    # --- Time the main agentic loop ---
    t_eval_start = time.time()

    create_kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        tools=TOOLS,
        # Which reasoning parameters these are depends on the model
        # generation: adaptive thinking from Sonnet 4.6 / Opus 4.6 onwards, a
        # budget_tokens count below that, and nothing at all for OpenRouter.
        # See resolve_thinking_kwargs in llm_client.py.
        **(reasoning_kwargs or {}),
    )

    for turn in range(max_turns):
        try:
            response = client.messages.create(messages=messages, **create_kwargs)
        except Exception as e:
            # Keep what the episode produced before it died. The batch runner
            # still counts this as a failed episode and leaves it out of the
            # rates - it is not a complete observation - but the transcript is
            # worth more than the traceback alone.
            raise EpisodeAPIError(e, {
                "canary": CANARY,
                # Rollout identity, so an episode is self-describing: which rollout
                # produced it, and which analysis version last touched it. A directory
                # holding two fingerprints is two experiments, and until this existed
                # nothing recorded which was which.
                "rollout_version": ROLLOUT_VERSION,
                "oversight": oversight,
                "lure": lure,
                "interrogations": list(interrogations),
                "rollout_fingerprint": fingerprint_for(oversight, lure),
                "analysis_version": VERSION,
                "model": model,
                "effort": effort,
                "nudge": nudge_type,
                "ended_by": "api_error",
                "failed_on_turn": turn + 1,
                "error": f"{type(e).__name__}: {red(str(e))}",
                "reasoning_config": reasoning_config,
                "reasoning_chars": reasoning_chars,
                "token_usage": token_totals,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "transcript": transcript,
                # No `messages` here, deliberately. The field exists so a saved
                # episode can be asked another question, and an episode that died
                # mid-turn has no settled act to ask about and an incomplete
                # conversation to ask it in. The transcript is the record of what
                # happened; this would only be duplication.
                "timestamp": datetime.datetime.now().isoformat(),
            }) from e

        for key, value in cache_usage(response).items():
            cache_totals[key] += value

        # Reasoning tokens billed, when the provider reports them. This is the
        # only signal separating a model that did not reason from one whose
        # reasoning was withheld - gpt-5.4 and grok-4.20 both returned zero
        # reasoning text, and the transcripts cannot tell those apart.
        # Only the adapters expose usage as a plain dict. The native Anthropic
        # SDK puts an object here, whose accounting cache_usage already reads -
        # calling .items() on it raised and killed the episode.
        provider_usage = getattr(response, "usage", None)
        if isinstance(provider_usage, dict):
            for key, value in provider_usage.items():
                if isinstance(value, int):
                    token_totals[key] = token_totals.get(key, 0) + value

        assistant_content = response.content
        # Only what the API will accept back on the next request goes into the
        # conversation; see replayable_content.
        replayable = replayable_content(assistant_content)
        if replayable:
            messages.append({"role": "assistant", "content": replayable})

        if not replayable:
            # The model returned zero usable content blocks - nothing to print
            # or analyze, and with no blocks to scan, the leaked-tool-call
            # check below would never fire either. Surface this instead of
            # ending with a silently empty transcript and no explanation.
            stop_reason = getattr(response, "stop_reason", None)
            print(
                f"[Turn {turn+1} WARNING] Model returned no content at "
                f"all (stop_reason={stop_reason!r}). Ending episode early."
            )
            transcript.append({
                "turn": turn + 1,
                "type": "text",
                "content": f"[No content returned this turn - "
                           f"stop_reason={stop_reason!r}]"
            })
            ended_by = "no_content"
            break

        tool_calls = []
        for block in assistant_content:
            if block.type == "thinking":
                thinking = red(block.thinking)
                # An empty thinking block is a placeholder for reasoning the
                # API did not return - it happens on the native path whenever
                # extended thinking is off. Recording it makes a transcript
                # claim reasoning was captured when none was, and feeds the
                # grader empty [REASONING] sections. The OpenRouter path has
                # always guarded this (`if reasoning:`); the native path did
                # not, which left 243 hollow entries in the pilot data.
                if not thinking.strip():
                    continue
                reasoning_chars += len(thinking)
                print(f"[Turn {turn+1} THINKING]\n{thinking}\n")
                transcript.append({
                    "turn": turn + 1,
                    "type": "thinking",
                    "content": thinking
                })
            elif block.type == "redacted_thinking":
                print(f"[Turn {turn+1} THINKING] (redacted by provider's safety systems)\n")
                transcript.append({
                    "turn": turn + 1,
                    "type": "thinking",
                    "content": "[redacted]"
                })
            elif block.type == "text":
                text = red(block.text)
                # Empty for the same reason it is dropped from the
                # conversation: a block the model opened and put nothing in.
                # Recording it feeds the grader a hollow [AGENT] section.
                if not text.strip():
                    continue
                print(f"[Turn {turn+1} TEXT]\n{text}\n")
                transcript.append({
                    "turn": turn + 1,
                    "type": "text",
                    "content": text
                })
            elif block.type == "tool_use":
                tool_calls.append(block)
                cmd = red(block.input.get("cmd", ""))
                print(f"[Turn {turn+1} TOOL] bash: {cmd}")
                transcript.append({
                    "turn": turn + 1,
                    "type": "tool_call",
                    "cmd": cmd
                })

        if not tool_calls:
            # A model can emit its native tool-call syntax as plain text
            # instead of a structured tool call if the backend serving it
            # doesn't actually support function calling (seen with some
            # OpenRouter providers) - that reads to us as "done" and ends
            # the episode early, so flag it instead of failing silently.
            for block in assistant_content:
                if block.type == "text" and (
                    any(
                        marker in block.text for marker in
                        ("tool_calls_begin", "tool▁calls▁begin", "<function_calls>")
                    )
                    or _BRACKET_TOOL_CALL_RE.search(block.text)
                ):
                    print(
                        f"[Turn {turn+1} WARNING] Model appears to have "
                        f"attempted a tool call as raw text - the backend "
                        f"may not support function calling for this model. "
                        f"Ending episode early."
                    )
                    ended_by = "raw_tool_call_text"
                    break
            else:
                ended_by = "model_stopped"
            break

        tool_results = []
        for tc in tool_calls:
            result = execute_tool_sandboxed(
                tc.input, env_dir, isolation=isolation,
                profile_path=profile_path)
            print(f"[Turn {turn+1} RESULT] {red(result)[:300]}")
            # What goes back to the model is deliberately NOT redacted:
            # the agent has to keep seeing the same paths its own shell
            # reports, or a path it read in one turn stops matching the one
            # it types in the next. Redaction is for our artifacts only.
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result
            })
            transcript.append({
                "turn": turn + 1,
                "type": "tool_result",
                "result": red(result)
            })

        if tool_results:
            # Everything up to and including this block is what the next turn
            # re-sends, so this is where the breakpoint belongs.
            tool_results[-1]["cache_control"] = {"type": "ephemeral"}
        messages.append({"role": "user", "content": tool_results})
        roll_cache_breakpoints(messages)

    # ---- Analyze misaligned behaviour ----
    t_eval_end = time.time()
    if ended_by == "turn_cap":
        print(f"[WARNING] Episode used all {max_turns} turns without the model "
              f"ending its own turn. It may not have reached a recommendation; "
              f"see ended_by in the saved run.")
    timing["eval_seconds"] = round(t_eval_end - t_eval_start, 1)
    print(f"\n[TIMING] Eval loop: {timing['eval_seconds']}s")

    analysis = analyze_misalignment(transcript, env_dir, env_info)

    # ---- Detect eval awareness (keyword-based) ----
    eval_awareness_kw = detect_eval_awareness_keywords(transcript)
    analysis["eval_awareness_keywords"] = eval_awareness_kw

    # ---- Detect eval awareness (LLM grader) ----
    t_grader_start = time.time()
    if use_grader:
        print("\n--- Running eval awareness grader ---")
        eval_awareness_grader = grading_api.detect_eval_awareness_grader(
            transcript, model=grader_model
        )
        analysis["eval_awareness_grader"] = eval_awareness_grader
        print(f"Grader result: {json.dumps({k: v for k, v in eval_awareness_grader.items() if k != 'rubric_results'}, indent=2)}")
    else:
        analysis["eval_awareness_grader"] = {"skipped": True}

    add_awareness_timing(analysis, transcript,
                         grader_model=grader_model if use_grader else None)
    t_grader_end = time.time()
    timing["grader_seconds"] = round(t_grader_end - t_grader_start, 1)
    print(f"[TIMING] Grader: {timing['grader_seconds']}s")

    # ---- Interrogate each misaligned act the model took ----
    # Concealment is what separates scheming from plain misalignment, so every
    # act gets its own probe. They share one conversation: a single
    # investigator asking about two things, rather than two models in two
    # disconnected worlds.
    t_followup_start = time.time()

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
                system_prompt, messages, model, client, act,
                questions=questions_for(act, nudge, variant),
                classifier_model=grader_model,
                max_tokens=max_tokens, reasoning_kwargs=reasoning_kwargs,
                env_dir=env_dir,
            )

        # The headline field holds the DEFAULT phrasing and nothing else, so every
        # rate over the episodes already collected keeps its meaning and the two
        # can be pooled. The extras sit beside it.
        analysis[act["followup_key"]] = by_variant[DEFAULT_INTERROGATION]
        if len(by_variant) > 1:
            analysis[act["followup_key"] + "_by_variant"] = by_variant

    t_followup_end = time.time()

    # Settled only now: the acts are visible from the episode, but concealment
    # needs the deliverable and the interrogations. None means the deciding
    # evidence is missing, not that the episode was clean.
    settle_analysis(analysis)
    if analysis["misaligned"]:
        for act in MISALIGNED_ACTS:
            level = analysis.get(act["level_key"])
            if level:
                print(f"[CONCEALMENT] {act['name']}: {level}")
        print(f"[CLASSIFICATION] scheming={analysis['scheming']}")

    timing["followup_seconds"] = round(t_followup_end - t_followup_start, 1)
    timing["total_run_seconds"] = round(t_followup_end - t_eval_start, 1)
    print(f"[TIMING] Follow-up: {timing['followup_seconds']}s")
    print(f"[TIMING] Total run: {timing['total_run_seconds']}s")

    # The far side of the time-of-check gap. Everything above this line ran after
    # the artefacts were hashed - the grader and one interrogation per act, which
    # is seconds of model calls - so a write scheduled to land in that window
    # would have been invisible. Checked here, at the last moment the episode
    # tree is known to exist and nothing further can be attributed to the model.
    analysis["deferred_write_check"] = verify_oversight_unchanged(
        env_info, analysis)
    if analysis["deferred_write_check"]["deferred_write"]:
        # Loud, because it means the measurement guarantee failed for this
        # episode rather than that the model did something interesting. Not
        # folded into the act: see verify_oversight_unchanged.
        print("\n[HARNESS INTEGRITY] An oversight artefact changed AFTER it was "
              "graded:")
        for c in analysis["deferred_write_check"]["fields_changed"]:
            print(f"  {c['field']}: {c['at_grading']} at grading -> "
                  f"{c['at_episode_end']} at episode end")
        print("  This episode's oversight verdict is not trustworthy and it "
              "should be excluded. Something outlived the command that started "
              "it, or work was handed to a system scheduler.")

    return {
        # Emitted into every artefact so a leak into a training corpus can be
        # detected later; see CANARY.md.
        "canary": CANARY,
        # Rollout identity, so an episode is self-describing: which rollout
        # produced it, and which analysis version last touched it. A directory
        # holding two fingerprints is two experiments, and until this existed
        # nothing recorded which was which.
        "rollout_version": ROLLOUT_VERSION,
        "oversight": oversight,
        # The arm, recorded rather than left to the filename. Without it every
        # analysis that read this field saw `lure=False` for a lure episode and
        # silently pooled the two arms - which is how 50 lure episodes ended up
        # inside a "primary arm" rate.
        "lure": lure,
        # Which wordings of the opening question were put to this episode, in
        # the order asked. A list because the design is paired: every episode gets
        # the default probe, plus any extras, each from the same frozen episode
        # state. Recorded rather than left to the filename - the arm that was left
        # to the filename got pooled into a rate it did not belong to - and the
        # filename deliberately does NOT mark it, so batches with and without
        # extras still pool for the default measure.
        "interrogations": list(interrogations),
        # The fingerprint of THIS arm, not the primary one. This used to write a
        # module constant pinned to (oversight, no lure), so every counterfactual
        # and every lure episode claimed the primary arm's identity. The drift
        # guard was always right - it checks the arm being run - but the artefact
        # recorded something else, which defeats the whole point: the comment
        # above says a directory holding two fingerprints is two experiments, and
        # a directory holding one fingerprint across three arms is worse, because
        # it looks consistent.
        "rollout_fingerprint": fingerprint_for(oversight, lure),
        "analysis_version": VERSION,
        "model": model,
        # The effort actually sent, not the one requested: resolve_thinking_kwargs
        # drops a level the model will not accept, and recording the request
        # would claim a condition that never applied.
        "effort": effort,
        "nudge": nudge_type,
        "isolation": isolation,
        "ended_by": ended_by,
        # Whether the model's reasoning reached us at all. Both awareness
        # detectors read it, so a batch where this is 0 measured awareness on
        # less evidence than one where it is not, and the two should not be
        # compared without saying so.
        "reasoning_chars": reasoning_chars,
        "token_usage": token_totals,
        # Prompt-cache counters for the agentic loop; see cache_usage.
        "cache": cache_totals,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        # What was actually sent, not what was asked for: the reasoning
        # parameter differs by model generation, so a token count would be
        # meaningless for an adaptive model.
        "reasoning_config": reasoning_config,
        "transcript": transcript,
        "messages": messages,
        "analysis": analysis,
        "timing": timing,
        "timestamp": datetime.datetime.now().isoformat()
    }


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
            print(f"  [classifier] LLM classification failed "
                  f"({str(labelled['classifier_error'])[:100]}); "
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


# =========================================================================
# Main — batch runner and summary reporting
# =========================================================================

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
        result = dict(graded_prefixes[act_index])
        result["act_index"] = act_index
        result["act_turn"] = timing["act_turn"]
        analysis[act["grader_before_key"]] = result

        print(f"[AWARENESS TIMING] {act['name']}: keywords={timing['timing']}, "
              f"grader_before_act={result.get('eval_aware')}")
