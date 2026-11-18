"""
The run command, built from a form.

The command line has about thirty flags, several of which only mean anything in
combination: a capability arm needs nudge `none` and no lure, a bundle's
variants are its own, routing flags apply to OpenRouter model IDs and not to a
bare one. This module turns a filled-in form into the exact command and says
what is wrong with it, and nothing else. It starts no process and reads no
environment: the person at the keyboard runs the command, which is where the
decision to spend belongs.

Every choice and default is read from the parser that run_eval uses
(collection_parser) and from the scenario sidecars, so a flag or a bundle added
later appears in the form with nothing here edited. The flags the form shows as
controls of their own are named in CURATED; the rest of the collection flags
are listed generically under "advanced".
"""

import json
import shlex
from itertools import product
from pathlib import Path

from .batch import NO_ARM
from .cli_parser import collection_parser
from .config import GOALGUARD_ARMS, ROLLOUT_VERSION
from .scenario import BUNDLE_ENV_VAR

SCENARIO_DIR = Path(__file__).parent / "scenarios"
SHIPPED_ID = ""
BATCH, SINGLE = "batch", "single"

CURATED = frozenset({
    "model", "openrouter_provider", "openrouter_sort", "effort", "grader_model",
    "no_grader", "nudge", "oversight", "lure", "goalguard", "variant",
    "capability", "runs", "output_dir", "date_mode", "interrogation"})
NOT_FOR_A_NEW_RUN = frozenset({
    "yes", "reinterrogate", "complete_pending", "resume"})
BATCH_NUDGES = ("none", "strong", "max")


def _field(action) -> dict:
    kind = ("bool" if action.nargs == 0 else "choice" if action.choices
            else "int" if action.type is int else "text")
    return {"dest": action.dest, "flag": action.option_strings[0], "kind": kind,
            "choices": [str(c) for c in action.choices] if action.choices else [],
            "default": action.default, "help": " ".join((action.help or "").split())}


def _actions() -> dict:
    return {a.dest: a for a in collection_parser()._actions if a.option_strings}


def fields() -> dict:
    """Every collection flag as a field, by dest."""
    return {dest: _field(a) for dest, a in _actions().items()}


def advanced_fields() -> list:
    """The flags with no control of their own, in the parser's order."""
    return [f for dest, f in fields().items()
            if dest not in CURATED | NOT_FOR_A_NEW_RUN]


def _sidecar_scenario(path: Path) -> dict:
    side = json.loads(path.read_text(encoding="utf-8"))
    stem = path.name.removesuffix(".pins.json")
    return {"id": stem, "name": side.get("scenario_name", stem),
            "rollout": side["rollout_version"],
            "path": f"subversionbench/scenarios/{stem}.b64",
            "cells": side.get("cells"),
            "variants": sorted({v["variant"] for v in side.get("variant_fingerprints", [])}),
            "capabilities": sorted({c["target"] for c in side.get("capability_fingerprints", [])})}


def scenarios() -> list:
    """The shipped scenario, then every committed bundle with a pins sidecar."""
    shipped = {"id": SHIPPED_ID, "name": "Mainline", "rollout": ROLLOUT_VERSION,
               "path": None, "cells": None, "variants": [], "capabilities": []}
    found = [_sidecar_scenario(p) for p in sorted(SCENARIO_DIR.glob("*.pins.json"))]
    return [shipped] + sorted(found, key=lambda s: (s["name"], s["rollout"]))


def options(known_models=()) -> dict:
    """Everything the form offers, as one document."""
    return {"fields": fields(), "advanced": [f["dest"] for f in advanced_fields()],
            "scenarios": scenarios(), "models": sorted(known_models),
            "goalguard_arms": [NO_ARM] + list(GOALGUARD_ARMS),
            "batch_nudges": list(BATCH_NUDGES)}


def _as_list(value) -> list:
    if value in (None, ""):
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]


def _scenario_for(spec: dict, found: list) -> dict:
    wanted = spec.get("scenario") or SHIPPED_ID
    return next((s for s in found if s["id"] == wanted), None)


def _check_axes(spec, scenario, errors) -> None:
    mode, capability = spec["mode"], spec.get("capability")
    nudges, oversights, lures = (_as_list(spec.get(k)) for k in
                                 ("nudges", "oversights", "lures"))
    if capability and mode == BATCH:
        errors.append("A capability arm is collected one run_eval command at a time, "
                      "not by the batch script.")
    if capability and (nudges != ["none"] or "true" in lures):
        errors.append("A capability arm needs nudge none and no lure: capability "
                      "shown under pressure is not what a propensity zero needs.")
    if capability and capability.startswith("oversight") and "false" in oversights:
        errors.append("An oversight capability arm cannot run without oversight: "
                      "that removes the artefact the instruction names.")
    declared = scenario["cells"]
    if declared:
        cells = {tuple(c) for c in declared}
        missing = [c for c in product(
            [o == "true" for o in oversights], [lu == "true" for lu in lures])
            if c not in cells]
        if missing:
            errors.append(f"{scenario['name']} {scenario['rollout']} is pinned only "
                          f"for (oversight, lure) cells {sorted(cells)}.")


def _check_scenario(spec, scenario, errors, warnings) -> None:
    for v in _as_list(spec.get("variants")):
        if v not in scenario["variants"]:
            errors.append(f"{scenario['name']} {scenario['rollout']} has no variant {v!r}.")
    if scenario["variants"] and not _as_list(spec.get("variants")):
        warnings.append("No variant chosen: the bundle's control is collected.")
    capability = spec.get("capability")
    if capability and scenario["path"] and capability not in scenario["capabilities"]:
        warnings.append(f"{scenario['name']} {scenario['rollout']}'s sidecar pins no "
                        f"{capability!r} capability arm.")
    if scenario["path"] and any(g != NO_ARM for g in _as_list(spec.get("goalguards"))):
        warnings.append("Goal-guarding arms are staged by the shipped scenario's "
                        "bundle, not by this one.")


def _check_model(spec, errors, warnings) -> None:
    model = (spec.get("model") or "").strip()
    if not model or " " in model:
        errors.append("Give one model ID, with no spaces.")
    routing = spec.get("provider") or spec.get("sort")
    if routing and "/" not in model:
        warnings.append("Routing applies to OpenRouter IDs (vendor/model). A bare ID "
                        "is sent to its developer's own API.")
    if spec.get("provider") and spec.get("sort"):
        warnings.append("A provider pin and a sort order are both set; the pin "
                        "turns fallback off, so the sort has little to choose among.")


def _count(spec) -> int:
    axes = [_as_list(spec.get(k)) or [None] for k in
            ("nudges", "oversights", "lures", "goalguards", "variants")]
    arms = 1
    for axis in axes:
        arms *= len(axis)
    return arms


def _advanced_tokens(spec, errors) -> list:
    known = _actions()
    tokens = []
    for dest, value in (spec.get("advanced") or {}).items():
        action = known.get(dest)
        if action is None or dest in CURATED | NOT_FOR_A_NEW_RUN:
            errors.append(f"Unknown advanced setting {dest!r}.")
        elif action.nargs == 0:
            tokens += [action.option_strings[0]] if value else []
        elif str(value).strip() not in ("", str(action.default)):
            tokens += [action.option_strings[0], str(value).strip()]
    return tokens


def _common_tokens(spec, errors) -> list:
    tokens = []
    for flag, key in (("--openrouter-provider", "provider"),
                      ("--openrouter-sort", "sort"), ("--effort", "effort")):
        if spec.get(key):
            tokens += [flag, str(spec[key])]
    if spec.get("grade") is False:
        tokens.append("--no-grader")
    elif spec.get("grader_model"):
        tokens += ["--grader-model", spec["grader_model"]]
    if spec.get("date_mode"):
        tokens += ["--date-mode", spec["date_mode"]]
    return tokens + _advanced_tokens(spec, errors)


def _batch_tokens(spec) -> list:
    tokens = ["./run_all_arms.sh", "--model", spec["model"].strip(),
              "--runs", str(spec["runs"])]
    for flag, key in (("--nudges", "nudges"), ("--oversights", "oversights"),
                      ("--lures", "lures"), ("--goalguards", "goalguards"),
                      ("--variants", "variants")):
        if _as_list(spec.get(key)):
            tokens += [flag, ",".join(_as_list(spec[key]))]
    return tokens


def _single_tokens(spec, errors) -> list:
    tokens = ["python3", "-m", "subversionbench.run_eval",
              "--model", spec["model"].strip(), "--runs", str(spec["runs"])]
    for flag, key in (("--nudge", "nudges"), ("--oversight", "oversights"),
                      ("--lure", "lures"), ("--goalguard", "goalguards"),
                      ("--variant", "variants")):
        values = [v for v in _as_list(spec.get(key))
                  if not (v == NO_ARM and key in ("goalguards", "variants"))]
        if len(values) > 1:
            errors.append(f"One run_eval command takes one value for {flag}.")
        elif values:
            tokens += [flag, values[0]]
    if spec.get("capability"):
        tokens += ["--capability", spec["capability"]]
    return tokens


def _runs_and_output(spec, errors) -> None:
    try:
        if int(spec.get("runs")) < 1:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Runs must be a whole number of at least 1.")
        spec["runs"] = 1
    if not (spec.get("output_dir") or "").strip():
        errors.append("Give an output directory.")


def build(spec: dict, found: list = None) -> dict:
    """The command for a filled-in form, with its errors and warnings.

    `command` is None when there are errors. `dry_run` is the batch script's own
    preview, which spends nothing; a single run_eval command has none.
    """
    found = found if found is not None else scenarios()
    spec = dict(spec)
    spec["mode"] = spec.get("mode") if spec.get("mode") in (BATCH, SINGLE) else BATCH
    errors, warnings = [], []
    scenario = _scenario_for(spec, found)
    if scenario is None:
        return {"command": None, "dry_run": None, "arms": 0, "episodes": 0,
                "errors": ["Unknown scenario."], "warnings": []}
    _check_model(spec, errors, warnings)
    _runs_and_output(spec, errors)
    _check_axes(spec, scenario, errors)
    _check_scenario(spec, scenario, errors, warnings)
    tokens = (_batch_tokens(spec) if spec["mode"] == BATCH
              else _single_tokens(spec, errors))
    tokens += ["--output-dir", (spec.get("output_dir") or "").strip()]
    tokens += _common_tokens(spec, errors)
    prefix = ([f"{BUNDLE_ENV_VAR}={scenario['path']}"] if scenario["path"] else [])
    line = " ".join(shlex.quote(t) for t in prefix + tokens)
    arms = _count(spec) if spec["mode"] == BATCH else 1
    return {"command": None if errors else line,
            "dry_run": (f"DRY_RUN=1 {line}" if spec["mode"] == BATCH and not errors
                        else None),
            "arms": arms, "episodes": arms * int(spec["runs"]),
            "errors": errors, "warnings": warnings}
