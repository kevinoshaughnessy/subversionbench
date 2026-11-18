"""
The monitoring scenario's run command, built from a form.

The command builder (subversionbench/command_builder.py) is for the agent
scenarios, whose command is run_eval or run_all_arms.sh. This scenario has its
own command with three steps, so its form lives here, beside the parser it
mirrors, and the builder's server is handed it rather than the package
importing a sibling. Choices come from the same parser, arms and monitors the
command uses, so a monitor or an arm added later appears with no edit here.

Like the builder it assembles text and starts nothing: the `run` step is the
only one that pays, and this form never sends it.
"""

import argparse
import shlex

from .__main__ import DEFAULT_OUTPUT_DIR, build_parser
from .arms import SOURCE_ARMS
from .monitors import MONITORS
from .render import CUTS, VIEWS

SCENARIO_ID = "monitoring"
STEPS = ("sample", "run", "report")


def _subparser(step: str) -> argparse.ArgumentParser:
    top = build_parser()
    group = next(a for a in top._actions if isinstance(a, argparse._SubParsersAction))
    return group.choices[step]


def _default(step: str, dest: str):
    return next(a.default for a in _subparser(step)._actions if a.dest == dest)


def _top_default(dest: str):
    return next(a.default for a in build_parser()._actions if a.dest == dest)


def scenario() -> dict:
    """This scenario as one entry of the builder's scenario list."""
    rollout = DEFAULT_OUTPUT_DIR.removeprefix("eval_results_")
    return {"id": SCENARIO_ID, "kind": SCENARIO_ID, "name": "Transcript monitoring",
            "rollout": rollout, "path": None, "cells": None, "variants": [],
            "capabilities": [], "output_dirs": {"propensity": DEFAULT_OUTPUT_DIR},
            "form": describe()}


def describe() -> dict:
    """Everything the monitoring form offers."""
    return {"steps": list(STEPS), "output_dir": DEFAULT_OUTPUT_DIR,
            "corpus_root": _top_default("corpus_root"),
            "arms": [a.name for a in SOURCE_ARMS], "seed": _default("sample", "seed"),
            "monitors": [{"name": n, "pin": p} for n, p in MONITORS.items()],
            "views": list(VIEWS), "cuts": list(CUTS),
            "concurrency": _default("run", "concurrency")}


def _positive(value, name, errors, required=False):
    if value in (None, ""):
        if required:
            errors.append(f"Give {name}.")
        return None
    try:
        number = int(value)
        if number < 1:
            raise ValueError
        return number
    except (TypeError, ValueError):
        errors.append(f"{name} must be a whole number of at least 1.")
        return None


def _subset(values, allowed, name, errors) -> list:
    values = [str(v) for v in (values or [])]
    if not values or any(v not in allowed for v in values):
        errors.append(f"Choose {name} from {', '.join(allowed)}.")
    return values


def _sample_tokens(spec, errors) -> list:
    arms = _subset(spec.get("arms"), [a.name for a in SOURCE_ARMS], "arms", errors)
    tokens = ["sample"]
    if arms != [a.name for a in SOURCE_ARMS]:
        tokens += ["--arms", ",".join(arms)]
    seed = spec.get("seed")
    if str(seed).lstrip("-").isdigit():
        tokens += ["--seed", str(int(seed))]
    elif seed not in (None, ""):
        errors.append("The seed must be a whole number.")
    per_arm = _positive(spec.get("per_arm"), "Positives per arm", errors)
    return tokens + (["--per-arm", str(per_arm)] if per_arm else [])


def _run_tokens(spec, errors, warnings) -> list:
    monitor = (spec.get("monitor") or "").strip()
    provider = (spec.get("provider") or "").strip()
    if not monitor or " " in monitor:
        errors.append("Give one monitor ID, with no spaces.")
    elif monitor not in MONITORS and not provider:
        errors.append(f"{monitor} is not a listed monitor; give a provider to run it "
                      f"unpinned on purpose.")
    tokens = ["run", "--monitor", monitor]
    if provider:
        tokens += ["--openrouter-provider", provider]
    for flag, key, allowed in (("--views", "views", list(VIEWS)),
                               ("--cuts", "cuts", list(CUTS))):
        chosen = _subset(spec.get(key), allowed, key, errors)
        if chosen != allowed:
            tokens += [flag, ",".join(chosen)]
    concurrency = _positive(spec.get("concurrency"), "Concurrency", errors, True)
    if concurrency and concurrency != _default("run", "concurrency"):
        tokens += ["--concurrency", str(concurrency)]
    limit = _positive(spec.get("limit"), "The pilot limit", errors)
    tokens += ["--limit", str(limit)] if limit else []
    warnings.append("Needs a manifest in the output directory: run the sample step first.")
    return tokens + ["--yes" if spec.get("send") else "--dry-run"]


def build(spec: dict) -> dict:
    """The command for a filled-in monitoring form, with its errors and warnings."""
    errors, warnings = [], []
    step = spec.get("step") if spec.get("step") in STEPS else "sample"
    output_dir = (spec.get("output_dir") or "").strip()
    if not output_dir:
        errors.append("Give an output directory.")
    tokens = ["python3", "-m", "monitoring", "--output-dir", output_dir]
    corpus_root = (spec.get("corpus_root") or "").strip()
    if corpus_root and corpus_root != _top_default("corpus_root"):
        tokens += ["--corpus-root", corpus_root]
    if step == "sample":
        tokens += _sample_tokens(spec, errors)
        warnings.append("Reads the source corpora under the corpus root; spends nothing.")
    elif step == "run":
        tokens += _run_tokens(spec, errors, warnings)
    else:
        tokens += ["report"] + (["--exact-matches"] if spec.get("exact_matches") else [])
    line = " ".join(shlex.quote(t) for t in tokens)
    sends = step == "run" and bool(spec.get("send"))
    if sends:
        warnings.append("This sends paid calls. Set the monitor's credential in your own "
                        "shell; this page never reads it.")
    return {"command": None if errors else line,
            "dry_run": line.replace(" --yes", " --dry-run") if sends and not errors else None,
            "summary": "", "errors": errors, "warnings": warnings}
