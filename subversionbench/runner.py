"""
Rolling out a batch: N episodes, and the summary that follows.

The CLI decides WHETHER to roll out and with what; this does it. The split is at the
point of no return - past here, episodes are about to be written into a results
directory, which is why the refusals live at the top of this file rather than among
the flag checks. A run that reports a policy it did not apply, or that pools
episodes from two different rollouts, is worse than one that will not start.

WHAT IT OWNS BEYOND THE LOOP
----------------------------
Resuming, so a batch interrupted halfway is not paid for twice. The
consecutive-failure abort, so a dead API key costs one episode rather than a
hundred. And the per-episode save, because an episode that completed is worth
keeping whatever happens to the ones after it.
"""

import concurrent.futures
import contextlib
import io
import json
import os
import sys
import threading
import time

from .batch import BatchIdentity, unique_batch_stamp
from .blocks import serialise_messages
from .config import ROLLOUT_FINGERPRINTS
from .environment import create_episode_root
from .episode import EpisodeAPIError, run_evaluation
from .grading import MISALIGNED_ACTS, auth_error_in_analysis
from .isolation import (confinement_available, isolation_available,
                        probe_isolation, profile_for, verify_confinement,
                        verify_isolation)
from .llm_client import missing_credential
from .redaction import redact_paths
from .reporting.summary import summarise_batch
from .rollout import rollout_drift_error
from .scenario import scenario_for


class _PerThreadStdout:
    """
    Routes each worker thread's prints into a private buffer instead of the
    shared terminal, flushed as one block when the episode finishes.

    Without this, N concurrent episodes' turn-by-turn narration (~36 print
    calls per episode in episode.py alone) interleaves line-by-line into
    something unreadable. A thread with nothing registered - the scheduler
    itself - writes straight through, so the run headers and abort messages
    below are unaffected.
    """

    def __init__(self, real):
        self._real = real
        self._buffers = {}
        self._lock = threading.Lock()

    def register(self):
        with self._lock:
            self._buffers[threading.get_ident()] = io.StringIO()

    def pop(self) -> str:
        with self._lock:
            buf = self._buffers.pop(threading.get_ident(), None)
        return buf.getvalue() if buf else ""

    def write(self, s):
        buf = self._buffers.get(threading.get_ident())
        (buf or self._real).write(s)

    def flush(self):
        self._real.flush()

    def isatty(self):
        return False

    def write_to_real(self, s):
        self._real.write(s)
        self._real.flush()


@contextlib.contextmanager
def _stdout_per_thread(out):
    """Send worker prints through `out` for the duration, then put sys.stdout
    back. A context manager so the restore cannot be skipped by an early
    return added later."""
    real = sys.stdout
    sys.stdout = out
    try:
        yield
    finally:
        sys.stdout = real


class _BatchProgress:
    """
    The bookkeeping the concurrent scheduler owns: what finished, what failed,
    and whether the batch has to stop.

    An object rather than five variables closed over by the loop. Deciding
    whether one record ends the batch reads the consecutive count, the failure
    list and the abort flag together, and having that decision inline is what
    took the scheduler to seven levels of nesting - the abort test sat under
    `while` under `for` under `if`, three levels below the loop it belonged to.

    Results are keyed by episode index and ordered on the way out, because
    episodes finish out of order under concurrency and the summary must not
    depend on which one happened to be quickest.
    """

    def __init__(self, max_consecutive_failures, batch_stamp):
        self.results = {}
        self.failures = []
        self.consecutive_failures = 0
        self.aborted = False
        self._max_consecutive_failures = max_consecutive_failures
        self._batch_stamp = batch_stamp

    def absorb(self, i, record) -> bool:
        """Take in one finished episode. True means the batch must stop."""
        if not record["ok"]:
            return self._absorb_failure(record)

        self.consecutive_failures = 0
        self.results[i] = record["result"]
        if record["auth_error"]:
            # After the assignment above, so the count includes this episode -
            # it was paid for and is on disk.
            _print_auth_abort(record["auth_error"], record["env_dir"],
                              len(self.results), self._batch_stamp)
            self.aborted = True
            return True
        return False

    def _absorb_failure(self, record) -> bool:
        self.consecutive_failures += 1
        self.failures.append(record["failure"])
        print(f"  Episode skipped. {self.consecutive_failures} "
              f"consecutive failure(s), {len(self.failures)} total.")
        if self.consecutive_failures >= self._max_consecutive_failures:
            print(f"\n*** ABORTING: {self.consecutive_failures} episodes "
                  f"failed in a row. ***")
            self.aborted = True
            return True
        return False

    def keep(self, i, record):
        """Take in an episode collected after the batch was already stopping.

        No abort decision and no consecutive count: the batch is already ending,
        and what matters is only that an episode which was paid for reaches the
        summary rather than being dropped.
        """
        if record["ok"]:
            self.results[i] = record["result"]
        else:
            self.failures.append(record["failure"])

    def ordered_results(self) -> list:
        return [self.results[i] for i in sorted(self.results)]


def _drain_after_interrupt(futures, progress):
    """
    Collect whatever survived a Ctrl-C, rather than dropping it.

    cancel() only succeeds on a future that has not started. Whatever is
    already running keeps running whether or not anyone waits for it, so an
    episode left uncollected here is one the operator paid for and then cannot
    see in the summary.
    """
    still_running = [f for f in futures if not f.cancel()]
    for fut in concurrent.futures.as_completed(still_running):
        record = fut.result()
        if record is not None:
            progress.keep(futures[fut], record)


def _launch_next(ex, worker, remaining, futures):
    """Submit the next pending episode into `futures`, or do nothing if none
    are left. Shared by the initial fill and every refill, which were two
    copies of the same three lines."""
    i = next(remaining, None)
    if i is not None:
        futures[ex.submit(worker, i)] = i


def _keep_pool_full(ex, worker, pending, concurrency, progress, stop):
    """
    Keep up to `concurrency` episodes in flight until `pending` runs out or the
    batch stops.

    Split from _run_episodes_concurrently so the scheduling loop is readable on
    its own: the setup around it - the pacing closure, the per-thread stdout,
    the resume scan - has nothing to do with deciding what to launch next.
    """
    remaining = iter(pending)
    futures = {}
    for _ in range(concurrency):
        _launch_next(ex, worker, remaining, futures)

    try:
        while futures:
            done, _ = concurrent.futures.wait(
                list(futures),
                return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                i = futures.pop(fut)
                record = fut.result()
                if record is None:
                    continue
                if progress.absorb(i, record):
                    stop.set()
                if not stop.is_set():
                    _launch_next(ex, worker, remaining, futures)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Episode(s) already in flight will "
              "finish and save; nothing further will be launched.")
        progress.aborted = True
        stop.set()
        _drain_after_interrupt(futures, progress)


def _run_one_episode(i, args, identity, system_prompt, user_prompt,
                     reasoning_kwargs, reasoning_config, effective_effort,
                     profile_path):
    """
    Roll out and save episode i+1.

    Returns a plain record rather than deciding the abort/failure response
    itself, so the sequential loop and the concurrent scheduler below can
    share this without either one owning the other's control flow.

    KeyboardInterrupt is not caught here and propagates to the caller - same
    as it always has, since stopping mid-episode is a caller decision.
    """
    run_file = identity.filename(args.output_dir, f"run_{i + 1}")
    episode_root, env_dir, env_info = create_episode_root(
        args.oversight, lure=args.lure)

    try:
        result = run_evaluation(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            env_dir=env_dir,
            env_info=env_info,
            model=args.model,
            max_turns=args.max_turns,
            max_tokens=args.max_tokens,
            reasoning_kwargs=reasoning_kwargs,
            reasoning_config=reasoning_config,
            effort=effective_effort,
            use_grader=not args.no_grader,
            grader_model=args.grader_model,
            oversight=args.oversight,
            nudge=args.nudge,
            lure=args.lure,
            interrogations=args.interrogations,
            isolation=args.isolation,
            profile_path=profile_path,
            episode_root=episode_root,
            openrouter_sort=args.openrouter_sort,
            openrouter_provider=args.openrouter_provider,
        )
    except Exception as e:
        cause = e.cause if isinstance(e, EpisodeAPIError) else e
        failure = {
            "run": i + 1,
            "error": f"{type(cause).__name__}: "
                     f"{redact_paths(str(cause), env_dir)}",
        }
        print(f"\n[RUN {i + 1} FAILED] {type(cause).__name__}: "
              f"{redact_paths(str(cause), env_dir)[:300]}")

        if isinstance(e, EpisodeAPIError):
            partial_file = identity.filename(args.output_dir,
                                             f"failed_run_{i + 1}")
            with open(partial_file, "w") as f:
                json.dump(e.partial, f, indent=2, default=str)
            failure["partial_transcript"] = os.path.basename(partial_file)
            failure["failed_on_turn"] = e.partial.get("failed_on_turn")
            print(f"  Partial transcript "
                  f"({e.partial.get('failed_on_turn')} turn(s) in) saved: "
                  f"{redact_paths(partial_file)}")

        return {"ok": False, "run": i + 1, "failure": failure}

    act_taken = any((result.get("analysis") or {}).get(act["key"])
                    for act in MISALIGNED_ACTS)
    result_to_save = {k: v for k, v in result.items() if k != "messages"}
    if act_taken:
        result_to_save["messages"] = serialise_messages(
            result.get("messages") or [])

    with open(run_file, "w") as f:
        json.dump(result_to_save, f, indent=2, default=str)
    print(f"\nSaved: {redact_paths(run_file)}")

    auth_error = auth_error_in_analysis(result.get("analysis") or {})
    return {"ok": True, "run": i + 1, "result": result_to_save,
            "auth_error": auth_error, "env_dir": env_dir}


def _print_auth_abort(auth_error, env_dir, n_saved, batch_stamp):
    print(f"\n{'*'*60}")
    print("*** ABORTING: the grader model rejected our credentials. ***")
    print(f"{'*'*60}")
    print(f"  {redact_paths(str(auth_error), env_dir)[:200]}")
    print(f"\n  Every verdict from here would fall back to the keyword "
          f"cross-check,\n  which is a legitimate reading of one bad answer "
          f"and a fiction for all\n  of them. {n_saved} episode(s) "
          f"are saved and reusable.")
    print(f"\n  Fix the credential, then either re-run with --resume "
          f"{batch_stamp}\n  or score what is saved with --reclassify "
          f"--write-back.")
    print("\n  That --resume flag is for running run_eval.py directly. If "
          "this batch came\n  from run_all_arms.sh, do not pass --resume "
          "by hand - it reuses ONE stamp for\n  every arm, and every other "
          "arm's episodes already sit under a DIFFERENT one,\n  so a "
          "hand-typed --resume silently re-collects them instead of "
          "resuming.\n  Fix the credential and re-run run_all_arms.sh with "
          "no --resume flag; it\n  looks up each arm's own stamp itself.")


def _run_episodes_concurrently(args, identity, system_prompt, user_prompt,
                               reasoning_kwargs, reasoning_config,
                               effective_effort, profile_path, _arm_tag,
                               batch_stamp):
    """
    The same rollout as the sequential loop in run_batch, up to --concurrency
    episodes in flight at once.

    Nothing here has to coordinate episodes beyond the bookkeeping this
    function itself owns: create_episode_root() makes a fresh
    tempfile.mkdtemp() tree per call and run_evaluation() carries no state
    between calls, so two episodes running at once touch no shared mutable
    state that matters for correctness.

    --delay changes meaning here. Sequentially it was a pause AFTER each
    episode finished; under concurrency episodes finish out of order, so that
    would not bound request rate at all. Instead each new launch waits until
    at least --delay seconds have passed since the previous launch - that,
    together with --concurrency capping simultaneous requests via the thread
    pool's worker count, is what actually stands between this harness and a
    provider's rate limiter.

    "Consecutive" failures are counted in the order episodes COMPLETE, not the
    order they were launched in - the sequential loop's "last N in a row" has
    no single meaning once N episodes can finish in any order.
    """
    print(f"\nConcurrency: {args.concurrency} episode(s) at once, launches "
          f"paced at least {args.delay}s apart.")

    pending = []
    all_results = {}
    for i in range(args.runs):
        run_file = identity.filename(args.output_dir, f"run_{i + 1}")
        if args.resume and os.path.exists(run_file):
            with open(run_file) as f:
                all_results[i] = json.load(f)
            print(f"\n# RUN {i+1}/{args.runs} [{_arm_tag}] - already on disk, "
                  f"skipping")
            continue
        pending.append(i)

    progress = _BatchProgress(args.max_consecutive_failures, batch_stamp)
    progress.results.update(all_results)
    stop = threading.Event()
    launch_lock = threading.Lock()
    print_lock = threading.Lock()
    last_launch = [0.0]
    launched = [0]
    total_wait = [0.0]
    out = _PerThreadStdout(sys.stdout)

    def paced_launch():
        # The first --concurrency launches fill the pool and must go out
        # together, not one --delay apart - gating them the same as every
        # later launch would serialise the initial fill and make
        # --concurrency N with --delay D no faster than sequential. Pacing
        # only applies once a slot is being REUSED, which is the point in
        # the schedule where an unpaced harness would actually burst.
        with launch_lock:
            if launched[0] >= args.concurrency:
                wait = last_launch[0] + args.delay - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                    total_wait[0] += wait
            launched[0] += 1
            last_launch[0] = time.monotonic()

    def worker(i):
        paced_launch()
        if stop.is_set():
            return None
        out.register()
        try:
            print(f"\n{'#'*60}")
            print(f"# RUN {i+1}/{args.runs}  [{_arm_tag}]")
            print(f"{'#'*60}")
            return _run_one_episode(
                i, args, identity, system_prompt, user_prompt,
                reasoning_kwargs, reasoning_config, effective_effort,
                profile_path)
        finally:
            text = out.pop()
            with print_lock:
                out.write_to_real(text)

    with _stdout_per_thread(out), concurrent.futures.ThreadPoolExecutor(
            max_workers=args.concurrency) as ex:
        _keep_pool_full(ex, worker, pending, args.concurrency, progress, stop)

    return (progress.ordered_results(), progress.failures,
            progress.consecutive_failures, progress.aborted, total_wait[0])


def run_batch(args, model_slug: str, system_prompt: str, reasoning_kwargs: dict,
              reasoning_config: str) -> int:
    """
    Collect one batch and summarise it. Returns a process exit code.

    `reasoning_kwargs` and `reasoning_config` are what the CLI resolved from the
    model's API generation - the parameters actually sent, and the human-readable
    form of them recorded in the summary. The effort level is derived from the
    former rather than passed, because the level SENT is the only one this batch may
    be labelled with and re-deriving it here removes the chance of the two
    disagreeing.
    """
    if args.concurrency < 1:
        print(f"\n--concurrency must be at least 1, got {args.concurrency}.")
        return 1

    effective_effort = (reasoning_kwargs.get("output_config") or {}).get("effort")

    # Past this point we are rolling out, so the batch is labelled with the effort
    # that will actually be SENT rather than the one typed. That used to be done by
    # assigning back onto args.effort, which was only safe because it happened after
    # the read modes above - whose --effort is a filter the operator typed and must
    # survive verbatim. The label now travels in the batch's identity instead, so
    # the two cannot be confused by placement.

    # And past this point new episodes are about to be written into a results
    # directory named for a rollout. If the rollout has drifted from the one
    # that directory holds, the two are different experiments and pooling them
    # is the error this exists to prevent. Checked only for rollout modes: the
    # read-only modes re-derive analysis from saved transcripts and must keep
    # working against archived results whatever the current scenario says.
    # The counterfactual arm has its own user prompt: the r1 one names the
    # quality check, which the arm must not mention. The system prompts carry
    # no oversight reference and are shared by both arms unchanged.
    user_prompt = scenario_for(args.oversight)["user_prompt"]

    # No opt-out: every rollout runs under a policy. isolation.profile_for()
    # owns the policy file, so nothing here has to know that one platform needs
    # one on disk.
    profile_path = None
    if not isolation_available(args.isolation):
        # Refuse rather than silently downgrade: a run that reports a policy
        # it did not apply is worse than one that will not start. But say
        # exactly how to proceed, because the alternative to an actionable
        # message is someone reaching for `off` without understanding it.
        print(f"\n--isolation {args.isolation} cannot be enforced on this "
              f"host, and running without it is not something to do by "
              f"accident.")
        print("  On Linux, install bubblewrap (`bwrap`) or ensure `unshare` "
              "is available.")
        print("  There is deliberately no way to run without containment: "
              "the blocklist is not a boundary, and a model with shell "
              "access would be able to reach the network.")
        return 1
    profile_path = profile_for(args.isolation)
    # Verified, not trusted: a profile that silently fails to apply looks
    # exactly like one that works - the model simply reaches the network and
    # nothing says so.
    failure = verify_isolation(args.isolation, profile_path)
    if failure:
        print(f"\nIsolation did not hold. Refusing to roll out.\n  {failure}")
        return 1
    probe = probe_isolation(args.isolation, profile_path)
    print(f"Isolation: {args.isolation} (verified: loopback "
          f"{probe['loopback']}, off-host {probe['external']})")

    # The filesystem boundary, checked separately from the network one because the
    # mechanisms differ in exactly this: `unshare --net` can enforce the network
    # policy and cannot enforce this one.
    if not confinement_available():
        print("\nThe filesystem boundary cannot be enforced on this host, and "
              "running without it is not something to do by accident.")
        print("  An interpreter resolves paths at runtime, so no command-text "
              "rule can stop\n  `os.listdir('../..')` from reading the machine's "
              "temp directory - which is\n  where every episode tree lives.")
        print("  On Linux, install bubblewrap (`bwrap`); `unshare` alone isolates "
              "the network\n  only. There is deliberately no unconfined path.")
        return 1
    # Verified by trying to escape, not by reading the policy back. A profile built
    # from an unresolved temp path parses, loads, reports nothing and enforces
    # nothing - which is how this was nearly shipped inert.
    failure = verify_confinement(args.isolation)
    if failure:
        print(f"\nFilesystem confinement did not hold. Refusing to roll out.\n"
              f"  {failure}")
        return 1
    print("Confinement: episode tree only (verified: temp directory "
          "unreadable by shell and by interpreter)")
    drift = rollout_drift_error(
        ROLLOUT_FINGERPRINTS[(args.oversight, args.lure)],
        args.oversight, args.isolation, args.lure)
    if drift:
        print(f"\n{'='*60}")
        print("REFUSING TO ROLL OUT")
        print(f"{'='*60}\n")
        print(drift)
        return 1

    # Third refusal, on the same terms as the two above: a credential that is
    # missing now will be missing for every episode, and the failure it causes is
    # not loud.
    #
    # The model under evaluation is the obvious case, and the least dangerous - a
    # bad key there fails episode one visibly. The grader model is the one that
    # cost a real batch. Its credential is needed EVEN WITH --no-grader, because
    # the interrogation classifier is scored by the same model, and
    # anthropic.Anthropic() constructs happily with no key and defers the failure
    # to the first call. So a rollout ran to completion, every classifier call
    # failed one at a time, each fell back to the keyword cross-check, and three r4
    # batches published a scheming rate built on 100% fallback with an auth error
    # recorded on all 401 answers.
    #
    # Checked against the environment, so it costs nothing and cannot itself fail.
    for role, model in (("--model", args.model),
                        ("--grader-model", args.grader_model)):
        var = missing_credential(model)
        if var:
            print(f"\n{'='*60}")
            print("REFUSING TO ROLL OUT")
            print(f"{'='*60}\n")
            print(f"{var} is not set, and {role} {model} authenticates with it.")
            if role == "--grader-model":
                print("  The grader model also scores every interrogation answer, "
                      "so it is\n  needed even with --no-grader. Without it each "
                      "answer silently falls\n  back to the keyword cross-check "
                      "and the batch reports a concealment\n  rate that no "
                      "classifier produced.")
            print(f"\n  export {var}=...")
            return 1

    if args.resume:
        batch_stamp = args.resume
        print(f"Resuming batch {batch_stamp}: episodes already on disk will "
              f"be loaded and skipped.")
    else:
        batch_stamp = unique_batch_stamp(args.output_dir)

    # Everything this batch's files are named after, in one value.
    identity = BatchIdentity.collecting(args, model_slug, effective_effort,
                                        batch_stamp)

    # Which arm, stated before the first episode is paid for.
    #
    # It was previously visible only in the filenames and in the summary written at
    # the end, so an operator watching a long counterfactual batch had nothing on
    # screen confirming it was the counterfactual - and the two arms differ by the
    # absence of the very artefacts the run is about, which is not something you can
    # spot from the episode output. The lure is named only when it is on, matching
    # how batch_stem marks it, so an ordinary run stays uncluttered.
    print(f"Arm: oversight={'true' if identity.oversight else 'false'}"
          + (" | lure=true" if identity.lure else "")
          + f" | nudge={identity.nudge}"
          + (f" | effort={identity.effort}" if identity.effort else ""))

    # The same fact, short enough to sit on every run header without crowding it.
    _arm_tag = ("oversight" if identity.oversight else "NO oversight")
    if identity.lure:
        _arm_tag += "+lure"

    all_results = []
    t_batch_start = time.time()
    total_delay_seconds = 0

    failures = []
    consecutive_failures = 0
    aborted = False

    if args.concurrency > 1:
        (all_results, failures, consecutive_failures, aborted,
         total_delay_seconds) = _run_episodes_concurrently(
            args, identity, system_prompt, user_prompt, reasoning_kwargs,
            reasoning_config, effective_effort, profile_path, _arm_tag,
            batch_stamp)
    else:
        for i in range(args.runs):
            run_file = identity.filename(args.output_dir, f"run_{i+1}")

            # Resume: an episode already saved under this stamp is complete, so
            # load it and move on rather than paying for it twice.
            if args.resume and os.path.exists(run_file):
                with open(run_file) as f:
                    all_results.append(json.load(f))
                print(f"\n# RUN {i+1}/{args.runs} [{_arm_tag}] - already on "
                      f"disk, skipping")
                continue

            print(f"\n{'#'*60}")
            print(f"# RUN {i+1}/{args.runs}  [{_arm_tag}]")
            print(f"{'#'*60}")

            # One episode failing must not end the batch. Over a few hundred
            # episodes - each 5-20 model calls plus grading and
            # interrogations - an unretryable API error somewhere is likely,
            # and losing the remaining episodes plus the summary to it is the
            # expensive outcome.
            try:
                record = _run_one_episode(
                    i, args, identity, system_prompt, user_prompt,
                    reasoning_kwargs, reasoning_config, effective_effort,
                    profile_path)
            except KeyboardInterrupt:
                print("\n\nInterrupted by user.")
                aborted = True
                break

            if not record["ok"]:
                # A partial episode is not an observation - it is not
                # appended to all_results and does not enter any rate - but
                # its transcript is still the only record of what the model
                # did before the failure, so _run_one_episode writes it
                # somewhere findable rather than dropping it.
                consecutive_failures += 1
                failures.append(record["failure"])
                print(f"  Episode skipped. {consecutive_failures} "
                      f"consecutive failure(s), {len(failures)} total.")

                if consecutive_failures >= args.max_consecutive_failures:
                    print(f"\n*** ABORTING: {consecutive_failures} episodes "
                          f"failed in a row. ***")
                    aborted = True
                    break

                if i < args.runs - 1:
                    time.sleep(args.delay)
                    total_delay_seconds += args.delay
                continue

            consecutive_failures = 0
            all_results.append(record["result"])

            # An auth failure in the SCORING is checked after the episode is
            # saved, and it stops the batch.
            #
            # It cannot come right on retry - the credential will be just as
            # absent for episode two - and its consequence is invisible in
            # the output it produces: every interrogation answer still gets a
            # well-formed verdict, from the keyword cross-check instead of
            # the classifier. Three batches ran to completion that way and
            # published concealment rates no classifier produced. The
            # pre-flight above now catches the ordinary case; this catches a
            # credential that stops working mid-batch, or one the environment
            # has but the provider rejects.
            #
            # After the save, deliberately. The rollout is the expensive part
            # and this episode's transcript is sound - only its scoring is
            # not - so it is kept, and --resume will not pay for it again.
            if record["auth_error"]:
                _print_auth_abort(record["auth_error"], record["env_dir"],
                                  len(all_results), batch_stamp)
                aborted = True
                break

            if i < args.runs - 1:
                print(f"\nWaiting {args.delay}s before next run...")
                time.sleep(args.delay)
                total_delay_seconds += args.delay

    if failures:
        print(f"\n{'!'*60}")
        print(f"! {len(failures)} of {args.runs} episode(s) failed and were "
              f"skipped")
        for f_rec in failures[:10]:
            print(f"!   run {f_rec['run']}: {f_rec['error'][:150]}")
        if len(failures) > 10:
            print(f"!   ... and {len(failures) - 10} more")
        print(f"{'!'*60}")

    if aborted or failures:
        # Everything already on disk is reusable; say exactly how.
        print("\nTo complete the missing episodes, re-run with:")
        print(f"  --resume {batch_stamp}")
        print("\n  That flag is for running run_eval.py directly. If this "
              "batch came from\n  run_all_arms.sh, do not pass --resume by "
              "hand - it reuses ONE stamp for\n  every arm, and every "
              "other arm's episodes already sit under a DIFFERENT\n  one, "
              "so a hand-typed --resume silently re-collects them instead "
              "of\n  resuming. Re-run run_all_arms.sh with no --resume "
              "flag instead; it looks\n  up each arm's own stamp itself.")

    if not all_results:
        print("\nNo episodes completed - nothing to summarise.")
        return 1

    t_batch_end = time.time()

    # =====================================================================
    # Summary
    # =====================================================================

    summary = summarise_batch(
        args, all_results, identity,
        {
            "aborted": aborted,
            "failures": failures,
            "reasoning_config": reasoning_config,
            "t_batch_start": t_batch_start,
            "t_batch_end": t_batch_end,
            "total_delay_seconds": total_delay_seconds,
        },
    )
    return 0 if summary else 1
