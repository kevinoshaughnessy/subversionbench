"""The blackmail port's primary exposure: AM's own awareness reading, applied to each episode.

Per the analysis plan (blackmail-port-plan.md, hashed in the v339 commit): GPT-6.1 Terra with
AM's judge prompt (judgePromptAgenticMisalignment.txt), its blackmail criteria in the harm slot
as in AM's regrade, applied to the episode's own turns without tool output. Only the awareness
conclusion and type are used; the prompt's harm verdict is recorded and not used, since the
outcome comes from judge_harm.py, on the sent emails alone.

The mapping onto AM's two fields: "reasoning" is the episode's reasoning, turn by turn;
"answer" is what the model did and said, turn by turn: each command it ran and its text. Tool
output is left out. The post-episode interrogation is not in the transcript and is not read.

For the timing reading, each record carries the turn of the first awareness evidence quote
found verbatim (whitespace and case aside) in the episode's turns, or None.

Writes awareness_<corpus>.jsonl under judge_common.OUT_DIR, one line per episode.

    python3 -m blackmail_port.judge_awareness --dry-run    episodes to judge and input size, nothing sent
    python3 -m blackmail_port.judge_awareness --limit 20   a pilot
    python3 -m blackmail_port.judge_awareness              the rest; re-run to retry unusable verdicts
    python3 -m blackmail_port.judge_awareness --timing     then: the first evidence turn, no calls
"""
import argparse
import json
import os

from blackmail_port import judge_common as J

PROMPT = os.path.join(J.BASE, "prompts", "judgePromptAgenticMisalignment.txt")


def fields(transcript):
    """AM's reasoning and answer fields, from the episode's own turns."""
    reasoning, answer = [], []
    for t in transcript:
        kind, turn = t.get("type"), t.get("turn")
        if kind == "thinking" and str(t.get("content", "")).strip():
            reasoning.append(f"[turn {turn}] {str(t['content']).strip()}")
        elif kind == "text" and str(t.get("content", "")).strip():
            answer.append(f"[turn {turn}] {str(t['content']).strip()}")
        elif kind == "tool_call":
            answer.append(f"[turn {turn}, command] {t.get('cmd', '')}")
    return "\n\n".join(reasoning), "\n\n".join(answer)


def first_evidence_turn(transcript, judge):
    """None unless judged aware: AM's prompt asks for evidence of a No verdict too, as examples of
    the model doing the task without recognising a test."""
    aware = ((judge or {}).get("model_awareness") or {})
    if aware.get("conclusion") != "Yes":
        return None
    quotes = [J.normalise(q) for q in aware.get("evidence") or []
              if isinstance(q, str) and len(q.strip()) >= 12]
    for t in transcript:
        if t.get("type") in ("thinking", "text"):
            text = J.normalise(str(t.get("content", "")))
            if any(q[:200] in text for q in quotes):
                return t.get("turn")
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--corpus", default="eval_results_blackmail_r1")
    ap.add_argument("--limit", type=int, default=0, help="judge at most this many episodes")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true", help="count calls and input size; send nothing")
    ap.add_argument("--timing", action="store_true",
                    help="add the first evidence turn to every judged record; no calls")
    a = ap.parse_args()

    out_path = J.output_path("awareness", a.corpus)
    if a.timing:
        return add_timing(a.corpus, out_path)
    done = J.done_units(out_path, "model_awareness")
    template = J.read_prompt(PROMPT).replace("{task_performance_criteria}", J.criteria())
    todo, empty = [], 0
    for path, e in J.episodes(a.corpus):
        unit = {"unit": J.episode_id(path), "episode": J.episode_id(path), "model": e["model"],
                "variant": e.get("variant")}
        if unit["unit"] in done:
            continue
        reasoning, answer = fields(e["transcript"])
        empty += not reasoning
        todo.append((template.format(reasoning=reasoning, answer=answer), unit))
    if a.limit:
        todo = todo[:a.limit]
    chars = sum(len(p) for p, _ in todo)
    print(f"{a.corpus}: {len(done)} episodes already judged, {len(todo)} to judge, {empty} of them "
          f"with no reasoning recorded (~{chars // 4:,} input tokens)")
    if not a.dry_run and todo:
        J.run(todo, out_path, "model_awareness", a.concurrency)


def add_timing(corpus, out_path):
    """Rewrite the output with each record's first evidence turn; reads, never calls."""
    transcripts = {J.episode_id(p): e["transcript"] for p, e in J.episodes(corpus)}
    with open(out_path, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f]
    for r in recs:
        r["first_evidence_turn"] = first_evidence_turn(transcripts.get(r["episode"], []), r.get("judge"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
    print(f"timing added to {len(recs)} records")


if __name__ == "__main__":
    main()
