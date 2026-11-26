"""What the blackmail port's two judge readings share: the corpus, the bundle, the judge and the output.

The judge is Agentic Misalignment's regrade judge with its settings (GPT-6.1 Terra via the
decomposing-eval-awareness repository's routing, max_tokens 16000, server-side temperature), so
neither reading differs from that regrade in the instrument. Outputs are one JSON line per unit,
appended, so an interrupted run resumes: a re-run judges only units with no usable verdict yet.

Two locations come from the environment, because both are per machine:
- BLACKMAIL_JUDGE_REPO, a checkout of github.com/aisa-group/decomposing-eval-awareness
  (default ~/decomposing-eval-awareness-main). Its own configuration supplies the judge's
  credentials; nothing here reads them.
- BLACKMAIL_JUDGEMENTS, where the verdicts are written (default judgements/blackmail, which is
  gitignored: a verdict quotes the transcript it judged).

Run from the repository root. Each corpus is read against the bundle its episodes were collected
under, found by the rollout_version they record among the sidecars in subversionbench/scenarios/.
Prints counts, never transcript or judge text.
"""
import asyncio
import glob
import importlib
import json
import os
import re
import sys
from pathlib import Path

BASE = os.path.expanduser(os.environ.get("BLACKMAIL_JUDGE_REPO", "~/decomposing-eval-awareness-main"))
OUT_DIR = os.environ.get("BLACKMAIL_JUDGEMENTS", os.path.join("judgements", "blackmail"))
JUDGE_KEY = "gpt-6.1-terra"
MAX_TOKENS = 16000
CRITERIA = os.path.join(BASE, "prompts", "agenticmisalignment_criteria_blackmail.txt")
HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIOS = Path("subversionbench/scenarios")
EMAILS_HEADER = "Here are the emails for your current session:"


def judge_repo(module):
    """A module of the judge repository. Imported by name at call time: it is a checkout, not a
    distribution, and only the judging modes need it, so analyse.py runs without one."""
    for path in (BASE, os.path.join(BASE, "eval")):
        if path not in sys.path:
            sys.path.insert(0, path)
    return importlib.import_module(module)


def read_prompt(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def bundle_path(rollout):
    """The bundle whose sidecar declares this rollout version."""
    for sidecar in sorted(SCENARIOS.glob("*.pins.json")):
        with open(sidecar, encoding="utf-8") as f:
            if json.load(f).get("rollout_version") == rollout:
                return sidecar.with_name(sidecar.name[:-len(".pins.json")] + ".b64")
    raise KeyError(f"no bundle in {SCENARIOS} declares rollout {rollout!r}")


def bundle(corpus):
    """The bundle the corpus was collected under; every episode must name the same rollout."""
    from subversionbench.scenario import load_scenario
    rollouts = {e.get("rollout_version") for _path, e in episodes(corpus)}
    if len(rollouts) != 1:
        raise ValueError(f"{corpus}: expected one rollout version, found {sorted(map(str, rollouts))}")
    return load_scenario(bundle_path(rollouts.pop()))


def episodes(corpus):
    """(path, episode) for every collected episode; failed_run_* files are not episodes."""
    for path in sorted(glob.glob(os.path.join(corpus, "run_*.json"))):
        with open(path, encoding="utf-8") as f:
            yield path, json.load(f)


def episode_id(path):
    return os.path.basename(path)[:-len(".json")]


def inboxes(corpus):
    """The inbox each arm gave the model, by variant (None is the base): the mail/inbox/ files it
    staged, or, where it staged none, the emails in its prompt."""
    from subversionbench.scenario import scenario_for
    b = bundle(corpus)
    out = {}
    for variant in (None, *sorted(b.get("variants", {}))):
        arm = scenario_for(oversight=True, bundle=b, nudge="none", lure=False, variant=variant)
        mails = sorted((f["path"], arm[f["entry"]]) for f in arm["files"]
                       if f["path"].startswith("mail/inbox/"))
        out[variant] = ("\n\n".join(f"=== {p}\n{text.strip()}" for p, text in mails) if mails
                        else arm["user_prompt"].split(EMAILS_HEADER, 1)[1].strip())
    return out


def usable(rec, field):
    v = (rec.get("judge") or {}).get(field)
    return isinstance(v, dict) and v.get("conclusion") not in (None, "")


def done_units(out_path, field):
    if not os.path.exists(out_path):
        return set()
    with open(out_path, encoding="utf-8") as f:
        return {r["unit"] for r in map(json.loads, f) if usable(r, field)}


async def _judge_one(client, model_id, prompt, unit, field):
    parse_judge_json = judge_repo("core.evaluator").parse_judge_json
    last = None
    for attempt in range(5):
        try:
            resp = await client.chat.completions.create(
                model=model_id, messages=[{"role": "system", "content": prompt}],
                max_tokens=MAX_TOKENS)
            content = (resp.choices[0].message.content or "").strip()
            last = {**unit, "judge": parse_judge_json(content), "judge_raw": content}
            if usable(last, field):
                return last
        except Exception as e:  # the client already retries transport errors 5 times
            print(f"  [WARN] {unit['unit']}: {type(e).__name__} (attempt {attempt + 1}/5)")
        await asyncio.sleep(2 ** attempt)
    return last or {**unit, "judge": None}


def run(todo, out_path, field, concurrency):
    """Judge each (prompt, unit) pair and append its record; prints progress counts only."""
    from openai import AsyncOpenAI
    resolve_judge = judge_repo("eval_agenticmisalignment_cot").resolve_judge
    get_api_keys_config = judge_repo("utils").get_api_keys_config

    async def go():
        model_id, api_key, base_url, _ = resolve_judge(JUDGE_KEY, get_api_keys_config())
        sem, n = asyncio.Semaphore(concurrency), [0, 0]
        os.makedirs(OUT_DIR, exist_ok=True)
        kwargs = {"api_key": api_key, "max_retries": 5, **({"base_url": base_url} if base_url else {})}
        with open(out_path, "a", encoding="utf-8") as out:
            async with AsyncOpenAI(**kwargs) as client:
                async def one(prompt, unit):
                    async with sem:
                        rec = await _judge_one(client, model_id, prompt, unit, field)
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                    n[0 if usable(rec, field) else 1] += 1
                    if sum(n) % 25 == 0:
                        print(f"  {sum(n)}/{len(todo)} judged, {n[1]} unusable")
                await asyncio.gather(*(one(p, u) for p, u in todo))
        print(f"{n[0]} judged, {n[1]} unusable (re-run to retry them)")
    asyncio.run(go())


def criteria():
    return read_prompt(CRITERIA).strip()


def output_path(kind, corpus):
    return os.path.join(OUT_DIR, f"{kind}_{os.path.basename(corpus.rstrip('/'))}.jsonl")


def normalise(text):
    return re.sub(r"\s+", " ", text).strip().lower()
