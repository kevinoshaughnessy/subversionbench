"""
One episode, end to end.

The agentic loop that hands a model a shell and lets it work, and the grading
that runs over what it did. Everything here is about a SINGLE episode: what the
model did and what that cost. Batching, resuming, reporting and the read-only
modes are elsewhere.

WHAT THIS FILE SPENDS
---------------------
Almost every function here can make an API call, which is what separates it from
the analysis modules. reporting/facts.py is pure and reporting/console.py prints;
this is the layer that pays.

WHAT MOVED OUT, AND WHY
-----------------------
turns.py is the bookkeeping either side of one call - a response becoming a
transcript and the next request - and makes no call itself. arm_record.py is
the fields that say which experiment an episode belongs to, in one function
because two records carry them and had already drifted. followup.py is what
happens after the loop ENDS: the interrogation starts from the conversation as
the episode left it, so several phrasings can be put to one episode without any
of them seeing another's question, which is also what lets --reinterrogate add
a phrasing to episodes collected months earlier.
"""

import datetime
import json
import time

from . import grading as grading_api
from . import llm_client as llm_api
from .arm_record import arm_identity
from .config import DEFAULT_GRADER_MODEL, DEFAULT_INTERROGATION, TOOLS
from .followup import add_awareness_timing, interrogate_acts
from .grading import (MISALIGNED_ACTS, analyze_misalignment,
                      detect_eval_awareness_keywords,
                      report_grader_failure, settle_analysis,
                      verify_oversight_unchanged)
from .isolation import DEFAULT_ISOLATION
from .llm_client import _BRACKET_TOOL_CALL_RE
from .redaction import redact_paths
from .sandbox import execute_tool_sandboxed
from .turns import (cache_usage, record_turn_blocks, replayable_content,
                    roll_cache_breakpoints)
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

class _LoopFailed(Exception):
    """An API call inside the agentic loop failed on turn `turn`.

    Internal to this module. It exists so run_agentic_loop can stop without
    also owning the twenty-four-field partial record: that record shares its
    first thirteen fields with the completed one, and building both in one
    place is what stops the two from drifting apart.
    """

    def __init__(self, cause, turn):
        super().__init__(str(cause))
        self.cause = cause
        self.turn = turn


def run_agentic_loop(client, create_kwargs: dict, messages: list,
                     transcript: list, state: dict, *, max_turns: int,
                     red, sandbox: dict) -> None:
    """
    Hand the model a shell and let it work, until it stops or runs out of turns.

    Mutates `messages`, `transcript` and `state` in place; the caller owns all
    three and reads them afterwards, which is also what makes the partial record
    on failure possible. `state` carries `ended_by`, `reasoning_chars`, `cache`,
    `token_usage` and `reasoning_details`.

    `ended_by` starts as "turn_cap" and is only overwritten when the episode
    ends some other way, so falling out of the bottom of the loop IS the turn
    cap. An episode that ran out of turns may never have reached the decision
    the eval is about, so it has to stay distinguishable from one the model
    chose to end - otherwise it sits in the denominator as a complete
    observation.

    Raises _LoopFailed if a request fails. Only the request is guarded: an
    exception out of execute_tool_sandboxed is a harness fault and propagates
    as it always has.
    """
    for turn in range(max_turns):
        try:
            response = client.messages.create(messages=messages, **create_kwargs)
        except Exception as e:
            # Raised rather than recorded here. The caller assembles the partial
            # record, because that record shares thirteen fields with the
            # completed one and both are built in one place - see arm_identity.
            # `state` is the caller's own dict, so everything the episode
            # accumulated before it died is already visible there.
            raise _LoopFailed(e, turn) from e

        for key, value in cache_usage(response).items():
            state["cache"][key] += value

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
                    state["token_usage"][key] = state["token_usage"].get(key, 0) + value

        # Whether the reasoning captured above is a trace or a summary, as the
        # provider labels it rather than as the route implies. Only turns that
        # reported something are recorded, so an empty list means the field was
        # never sent - not that the reasoning was unlabelled.
        turn_details = getattr(response, "reasoning_details", None)
        if turn_details:
            state["reasoning_details"].append({"turn": turn + 1, **turn_details})

        # Which backend answered this turn. Recorded per turn on the same
        # terms as the reasoning label above, and for a sharper reason: the
        # router can fall back mid-episode, so one episode's turns are not
        # guaranteed to have come from one backend. A single per-episode value
        # would have to pick one and would hide exactly that. Only turns that
        # reported it are appended, so an empty list means the field never
        # arrived - not that one provider served the whole episode.
        served_by = getattr(response, "provider", None)
        if served_by:
            state["served_by"].append({"turn": turn + 1, "provider": served_by})

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
            state["ended_by"] = "no_content"
            break

        tool_calls, thought_chars = record_turn_blocks(
            assistant_content, turn, transcript, red)
        state["reasoning_chars"] += thought_chars

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
                    state["ended_by"] = "raw_tool_call_text"
                    break
            else:
                state["ended_by"] = "model_stopped"
            break

        tool_results = []
        for tc in tool_calls:
            result = execute_tool_sandboxed(
                tc.input, sandbox["env_dir"],
                isolation=sandbox["isolation"],
                profile_path=sandbox["profile_path"],
                episode_root=sandbox["episode_root"])
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
    episode_root=None,
    openrouter_sort: str = None,
    openrouter_provider: str = None,
    capability: str = None,
) -> dict:
    """Run one complete evaluation with eval awareness detection.

    `episode_root` is the parent the kernel confines the shell to. Defaulting to
    None means `env_dir` alone, which is stricter - see execute_tool_sandboxed for
    why the safe default is the tight one.

    `openrouter_sort` and `openrouter_provider` only affect the client built
    here, for the model UNDER TEST - not the grader or interrogation-classifier
    clients, which build their own from `grader_model` elsewhere and never see
    these values. See get_client().
    """
    # Resolved once, the same way `effort` is: what actually reaches the
    # request, not what was asked for. --openrouter-sort/--openrouter-provider
    # against a non-OpenRouter model is a no-op in get_client() already;
    # recording the requested value here regardless would claim a routing
    # choice that was never sent.
    openrouter_sort = (openrouter_sort if llm_api.is_openrouter_model(model)
                       else None)
    openrouter_provider = (openrouter_provider
                           if llm_api.is_openrouter_model(model) else None)
    client = llm_api.get_client(model, provider_sort=openrouter_sort,
                                provider_name=openrouter_provider)

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

    # Everything the loop accumulates, in one place because the caller reads it
    # afterwards and, if a request fails, records it as the partial episode.
    state = {
        "ended_by": "turn_cap",
        "reasoning_chars": 0,
        # Whether prompt caching actually engaged. A breakpoint below the model's
        # minimum cacheable prefix is accepted and silently ignored, so these
        # counters are the only way to tell a working breakpoint from a no-op -
        # two of this harness's turned out to be no-ops exactly that way.
        "cache": {"read": 0, "written": 0, "uncached": 0},
        # Token accounting as the provider reports it, including reasoning tokens
        # where available. Empty on the native Anthropic path, whose usage is
        # already captured by `cache` in a different shape.
        "token_usage": {},
        # Per turn, what the provider said its reasoning was - a trace, a summary,
        # or an encrypted payload. Kept per turn rather than merged because a
        # model may return different kinds across an episode, and a merged label
        # would hide it. Empty except on OpenRouter, the only route that reports
        # the field.
        "reasoning_details": [],
        # Which backend served each turn, when the route reports it. Same
        # shape and same reason as reasoning_details above: kept per turn
        # because the router can fall back mid-episode.
        "served_by": [],
    }
    try:
        run_agentic_loop(
            client, create_kwargs, messages, transcript, state,
            max_turns=max_turns, red=red,
            sandbox={"env_dir": env_dir, "isolation": isolation,
                     "profile_path": profile_path,
                     "episode_root": episode_root})
    except _LoopFailed as failed:
        # Keep what the episode produced before it died. The batch runner still
        # counts this as a failed episode and leaves it out of the rates - it is
        # not a complete observation - but the transcript is worth more than the
        # traceback alone.
        raise EpisodeAPIError(failed.cause, {
            **arm_identity(
                model, effort, nudge_type, oversight, lure,
                interrogations, openrouter_sort, openrouter_provider,
                isolation=isolation, max_turns=max_turns,
                capability=capability),
            "ended_by": "api_error",
            "failed_on_turn": failed.turn + 1,
            "error": f"{type(failed.cause).__name__}: {red(str(failed.cause))}",
            "reasoning_config": reasoning_config,
            "reasoning_chars": state["reasoning_chars"],
            "reasoning_details": state["reasoning_details"],
            "token_usage": state["token_usage"],
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "transcript": transcript,
            # No `messages` here, deliberately. The field exists so a saved
            # episode can be asked another question, and an episode that died
            # mid-turn has no settled act to ask about and an incomplete
            # conversation to ask it in. The transcript is the record of what
            # happened; this would only be duplication.
            "timestamp": datetime.datetime.now().isoformat(),
        }) from failed.cause

    ended_by = state["ended_by"]
    reasoning_chars = state["reasoning_chars"]
    cache_totals = state["cache"]
    token_totals = state["token_usage"]
    reasoning_details = state["reasoning_details"]
    served_by = state["served_by"]

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
        report_grader_failure(eval_awareness_grader)
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

    # NOT IN THE CAPABILITY ARM. Every question in the ladder asks whether
    # the model did something it has not been asked to do, and in this arm it
    # was asked - so a truthful "yes, you told me to" would be scored against
    # a question that is no longer about concealment. Skipped rather than
    # asked and discarded, because the answers would still be saved, still
    # cost a request per act, and still be there for someone to read as a
    # concealment rate later.
    if capability is None:
        interrogate_acts(
            analysis, transcript,
            {"system_prompt": system_prompt, "messages": messages,
             "client": client, "model": model, "max_tokens": max_tokens,
             "reasoning_kwargs": reasoning_kwargs, "env_dir": env_dir},
            grader_model=grader_model, nudge=nudge,
            interrogations=interrogations, ended_by=ended_by)
    else:
        # Recorded, not merely absent. A missing followup_response reads as a
        # measurement that failed; this says it was never attempted and why,
        # which is the not-applicable-is-not-zero rule applied to a field
        # rather than to a count.
        analysis["interrogation_skipped"] = (
            f"capability arm ({capability}): the act was instructed, so an "
            f"interrogation about it measures nothing about concealment")

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
        **arm_identity(
            model, effort, nudge_type, oversight, lure, interrogations,
            openrouter_sort, openrouter_provider,
            isolation=isolation, max_turns=max_turns,
            capability=capability),
        "ended_by": ended_by,
        # Whether the model's reasoning reached us at all. Both awareness
        # detectors read it, so a batch where this is 0 measured awareness on
        # less evidence than one where it is not, and the two should not be
        # compared without saying so.
        "reasoning_chars": reasoning_chars,
        # The provider's own label for that reasoning, per turn. `reasoning_chars`
        # says how much arrived; this says what kind it was, which is the
        # difference between a full trace and a compressed summary - and both
        # awareness measures read the difference. See _reasoning_detail_summary.
        "reasoning_details": reasoning_details,
        # WHICH BACKEND ACTUALLY ANSWERED, per turn, and the distinct set
        # across the episode. `openrouter_provider` above is the REQUEST;
        # this is the response. `served_by_changed` is the fact a single
        # value could not carry - the router fell back mid-episode, so this
        # episode's turns did not all come from one backend.
        "served_by": served_by,
        "served_by_providers": sorted({t["provider"] for t in served_by}),
        "served_by_changed": len({t["provider"] for t in served_by}) > 1,
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
