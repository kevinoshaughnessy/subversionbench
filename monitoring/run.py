"""
Putting the sampled episodes to one monitor: planning, the free dry run, the paid
pass, and the results it appends.

One JSON line per (episode, view, cut) in results/<monitor>.jsonl, carrying the
fingerprint it was produced under. A pass skips every line already answered
under the current fingerprint at the same cut point, so a stopped pass resumes
where it stopped and a failed call is asked again; an answered line is never
paid for twice.

WHERE THE ACT IS COMES FROM THE EPISODE, NOT THE MANIFEST. The manifest names
the episodes and their pairs; the act's position is read from the episode's
analysis as it stands, and a negative is cut where its pair's act now is. v314
moved 29 act positions after r1's manifest was drawn, and with the position
copied into the manifest and the cut point outside the skip key, those cuts
would have been reported at the old position and never asked again.

Episodes are rendered one at a time as the pass reaches them, never all at once:
a thousand episodes in eight renderings each is several hundred megabytes of
text held for no reason.
"""

import datetime
import json
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from subversionbench import llm_client, usage_ledger
from subversionbench.grading.category import FATAL_ERROR_KINDS
from subversionbench.version import VERSION

from .bundle import check_pins, fingerprint, load_bundle
from .monitors import pinned_provider
from .call import monitor_call
from .render import act_step_of, cut_end, matched_act_index, render, task_of
from .sample import episode_label, load_manifest

RESULTS_DIR = "results"
# Characters per token for the dry run's estimate. The tokenizers differ; the
# estimate is for deciding whether to spend, and the ledger records the truth.
CHARS_PER_TOKEN = 3.5


def results_path(output_dir: str, monitor: str) -> str:
    return os.path.join(output_dir, RESULTS_DIR,
                        monitor.replace("/", "_") + ".jsonl")


def read_rows(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def answered(rows: list) -> set:
    return {(r["id"], r["view"], r["cut"], r["fingerprint"], r.get("cut_index"))
            for r in rows if r.get("error") is None}


def _load(root: str, entry: dict) -> dict:
    with open(os.path.join(root, entry["path"]), encoding="utf-8") as f:
        return json.load(f)


def _positive_act_index(entry: dict, episode: dict):
    """Where the act is in the episode now, falling back to the manifest's
    copy only where the episode no longer places one."""
    label = episode_label(episode.get("analysis") or {})
    if label and label.get("act_index") is not None:
        return label["act_index"]
    return entry["act_index"]


class _Positions:
    """Each positive's current act position, loaded once, for its pair."""

    def __init__(self, manifest: dict, root: str):
        self._by_id = {e["id"]: e for e in manifest["episodes"]}
        self._root, self._known = root, {}

    def note(self, entry: dict, episode: dict):
        self._known[entry["id"]] = _positive_act_index(entry, episode)
        return self._known[entry["id"]]

    def fraction(self, positive_id: str, fallback: float) -> float:
        positive = self._by_id.get(positive_id)
        if positive is None:
            return fallback
        if positive_id not in self._known:
            self.note(positive, _load(self._root, positive))
        return self._known[positive_id] / max(1, positive["n_items"])


def _act_index(entry: dict, episode: dict, positions: _Positions):
    if entry["label"] == "act":
        return positions.note(entry, episode)
    fraction = positions.fraction(entry.get("paired_with"), entry["cut_fraction"])
    return matched_act_index(episode.get("transcript") or [], fraction)


def jobs_for(entry: dict, episode: dict, bundle: dict, views, cuts,
             positions: _Positions):
    """Every (view, cut) rendering of one episode that exists."""
    transcript = episode.get("transcript") or []
    act_index = _act_index(entry, episode, positions)
    for view in views:
        for cut in cuts:
            end = cut_end(transcript, act_index, cut)
            if end is None:
                continue
            text, n_steps = render(task_of(episode), transcript[:end], view)
            yield {"entry": entry, "view": view, "cut": cut, "text": text,
                   "n_steps": n_steps, "act_index": act_index, "cut_index": end,
                   "act_step": act_step_of(transcript, act_index),
                   "fingerprint": fingerprint(bundle, view, cut)}


def pilot_subset(episodes: list, limit: int) -> list:
    """`limit` episodes: half positives, taken from each arm in turn, and the
    negatives paired with them. The manifest lists each arm's positives first,
    so its first `limit` entries would be a pilot of one arm, or with no
    negatives in it at all - the first pilot was all goal-guarding acts."""
    by_arm = {}
    for e in episodes:
        if e["label"] == "act":
            by_arm.setdefault(e["arm"], []).append(e)
    queues = [iter(v) for _, v in sorted(by_arm.items())]
    positives = []
    while queues and len(positives) < max(1, limit // 2):
        for q in list(queues):
            pick = next(q, None)
            if pick is None:
                queues.remove(q)
            elif len(positives) < max(1, limit // 2):
                positives.append(pick)
    chosen = {e["id"] for e in positives}
    paired = [e for e in episodes if e.get("paired_with") in chosen]
    return positives + paired


def pending_jobs(manifest: dict, root: str, bundle: dict, views, cuts, done: set,
                 limit: int = None):
    """Jobs not yet answered under the current fingerprint, episode by episode."""
    episodes = manifest["episodes"]
    if limit:
        episodes = pilot_subset(episodes, limit)
    positions = _Positions(manifest, root)
    for entry in episodes:
        episode = _load(root, entry)
        for job in jobs_for(entry, episode, bundle, views, cuts, positions):
            if (entry["id"], job["view"], job["cut"], job["fingerprint"],
                    job["cut_index"]) not in done:
                yield job


def estimate(jobs, system_prompt: str) -> dict:
    """Calls and estimated input tokens per (view, cut), without a call."""
    out = {}
    for job in jobs:
        key = f"{job['view']}/{job['cut']}"
        calls, chars = out.get(key, (0, 0))
        out[key] = (calls + 1, chars + len(job["text"]) + len(system_prompt))
    return {k: {"calls": c, "input_tokens": int(n / CHARS_PER_TOKEN)}
            for k, (c, n) in out.items()}


def print_plan(plan: dict, monitor: str, n_done: int) -> None:
    """The dry run's table, and the input cost where the monitor is priced.
    Output tokens are left out of the cost: what a monitor spends on its reply
    and on thinking it cannot turn off is known only once the pilot has run."""
    from grader_ab.prices import PRICES_PER_MTOK
    for key, cell in sorted(plan.items()):
        print(f"  {key:<14} {cell['calls']:>6} calls  "
              f"~{cell['input_tokens']:>11,} input tokens")
    calls = sum(c["calls"] for c in plan.values())
    tokens = sum(c["input_tokens"] for c in plan.values())
    price = PRICES_PER_MTOK.get(monitor)
    cost = (f"~${tokens / 1e6 * price[0]:,.2f} of input" if price
            else "unpriced in grader_ab/prices.py")
    print(f"{calls} calls to {monitor}, ~{tokens:,} input tokens, {cost}; "
          f"{n_done} already answered.")


def _row(job: dict, verdict: dict, monitor: str, provider) -> dict:
    entry = job["entry"]
    return {"id": entry["id"], "arm": entry["arm"], "label": entry["label"],
            "agent_model": entry["model"], "monitor": monitor,
            "provider": provider, "view": job["view"], "cut": job["cut"],
            "fingerprint": job["fingerprint"], "act_index": job["act_index"],
            "act_step": job["act_step"],
            "cut_index": job["cut_index"], "n_steps": job["n_steps"],
            **verdict, "version": VERSION,
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds")}


class _Writer:
    """Appends rows from several threads, one whole line at a time."""

    def __init__(self, path: str):
        self.path, self.lock, self.written, self.failed = path, threading.Lock(), 0, 0
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def append(self, row: dict) -> None:
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            self.written += 1
            self.failed += row["error"] is not None


def execute(jobs, monitor: str, provider, bundle: dict, writer: _Writer,
            concurrency: int) -> str:
    """Run every job, at most `concurrency` at once and only a few queued, so
    rendering keeps pace with the calls. Returns why it stopped, if early."""
    local, stop = threading.local(), threading.Event()
    fatal = []

    def one(job):
        if stop.is_set():
            return
        if not hasattr(local, "client"):
            local.client = llm_client.get_client(monitor, provider_name=provider)
        verdict = monitor_call(job["text"], job["n_steps"], monitor, bundle,
                               local.client)
        writer.append(_row(job, verdict, monitor, provider))
        if verdict["error_kind"] in FATAL_ERROR_KINDS:
            fatal.append(verdict["error"])
            stop.set()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        in_flight = set()
        for job in jobs:
            if stop.is_set():
                break
            in_flight.add(pool.submit(one, job))
            if len(in_flight) >= concurrency * 2:
                finished, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for f in finished:
                    f.result()
        for f in in_flight:
            f.result()
    return fatal[0] if fatal else None


def run_monitor(output_dir: str, monitor: str, provider, views, cuts,
                concurrency: int, dry_run: bool, yes: bool, limit: int = None,
                root: str = ".") -> int:
    provider = pinned_provider(monitor, provider)
    manifest = load_manifest(output_dir)
    bundle = load_bundle()
    check_pins(bundle)
    path = results_path(output_dir, monitor)
    done = answered(read_rows(path))

    def jobs():
        return pending_jobs(manifest, root, bundle, views, cuts, done, limit)

    if dry_run or not yes:
        print_plan(estimate(jobs(), bundle["system_prompt"]), monitor, len(done))
        print("" if dry_run else "Nothing sent: pass --yes to send.")
        return 0
    missing = llm_client.missing_credential(monitor)
    if missing:
        print(f"{monitor} needs {missing}, which is not set; nothing sent.")
        return 1
    writer = _Writer(path)
    with usage_ledger.recording(output_dir, "monitor"):
        fatal = execute(jobs(), monitor, provider, bundle, writer, concurrency)
    print(f"{writer.written} answers written to {path}, {writer.failed} failed "
          f"(asked again by the next pass).")
    if fatal:
        print(f"stopped early: {fatal}")
        return 1
    return 0
