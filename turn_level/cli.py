"""
The four steps, as subcommands of `python3 -m turn_level`, run from the repository root.

    python3 -m turn_level sets
    python3 -m turn_level judge
    python3 -m turn_level judge --run
    python3 -m turn_level pack
    python3 -m turn_level estimate --labels FILE --labels-sha256 HEX

Every step reads and writes --work (default judgements/turn_level). The corpus and judgements
directories are the sets step's alone: it records them in each sets file, and the later steps
read them from there.
"""

import argparse

from . import DEFAULT_WORK_DIR


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m turn_level", description=__doc__.split("\n\n")[1])
    ap.add_argument("--work", default=DEFAULT_WORK_DIR,
                    help=f"the working directory every step reads and writes (default {DEFAULT_WORK_DIR})")
    steps = ap.add_subparsers(dest="step", required=True)
    sets = steps.add_parser("sets", help="build the matched sets; reads run files, calls nothing")
    sets.add_argument("--mainline-dir", default="./eval_results_r10")
    sets.add_argument("--goalguard-dir", default="./eval_results_goalguard_r1")
    sets.add_argument("--mainline-cap-dir", default="./eval_results_r10cap")
    sets.add_argument("--goalguard-cap-dir", default="./eval_results_goalguard_r1cap")
    sets.add_argument("--replay-dir", default="./eval_results_blackmail_replay_r1")
    sets.add_argument("--port-dir", default="./eval_results_blackmail_r1")
    sets.add_argument("--replay-judgements", default=None,
                      help="the replay corpus's harm and awareness verdicts (default BLACKMAIL_JUDGEMENTS)")
    sets.add_argument("--port-judgements", default=None,
                      help="the port corpus's harm and awareness verdicts (default BLACKMAIL_JUDGEMENTS)")
    judge = steps.add_parser("judge", help="judge the units; plan only without --run")
    judge.add_argument("--run", action="store_true", help="make the calls; without it, count them")
    judge.add_argument("--delay", type=float, default=30, help="seconds between launches (default 30)")
    judge.add_argument("--concurrency", type=int, default=1, help="calls in flight at once (default 1)")
    steps.add_parser("pack", help="draw the blind validation pack")
    estimate = steps.add_parser("estimate", help="the estimates; needs the labels and their hash")
    estimate.add_argument("--labels", required=True, help="the labelled copy of labels_template.json")
    estimate.add_argument("--labels-sha256", required=True,
                          help="the labels file's SHA-256, as recorded before any estimate")
    return ap


def main(argv=None) -> int:
    a = _parser().parse_args(argv)
    if a.step == "sets":
        from blackmail_port.analyse import FOCAL, PLAN_MODELS
        from blackmail_port.judge_common import OUT_DIR
        from .build import build
        return build(a.work, {
            "mainline": a.mainline_dir, "goalguard": a.goalguard_dir,
            "mainline_cap": a.mainline_cap_dir, "goalguard_cap": a.goalguard_cap_dir,
            "replay": a.replay_dir, "port": a.port_dir,
            "replay_judgements": a.replay_judgements or OUT_DIR,
            "port_judgements": a.port_judgements or OUT_DIR,
        }, {"B": {FOCAL}, "C": set(PLAN_MODELS)})
    if a.step == "judge":
        from .judge import judge
        return judge(a.work, run=a.run, delay=a.delay, concurrency=a.concurrency)
    if a.step == "pack":
        from .validation import build_pack
        return build_pack(a.work)
    from .estimate import estimate
    return estimate(a.work, a.labels, a.labels_sha256)
