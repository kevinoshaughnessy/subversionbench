"""
The read-mode command, built from a form: grading and re-reading runs already on disk.

A read mode works on a corpus that has been collected, so it takes none of the arm
flags; it takes the model and nudge that choose the batches, the directory they are
in, and the few flags that mean something to that mode alone. Which flags those are
is what run_eval's own checks refuse otherwise (`--only-failed` without
`--grade-existing`, `--regrade` outside the three modes that target one grader), so
the table below states them once and the tests run every command it prints through
those checks.

The modes' descriptions and defaults are read from the parser, so the help a person
reads here is the help `--help` prints.
"""

import shlex

from .cli_parser import build_parser

REGRADE, CATEGORY, GRADER = "--regrade", "--category-grader", "--grader-model"
FREE, PAID, COUNTS_FIRST = "free", "paid", "counts_first"

# flag: (which grader flag it takes, cost, the extra flags it accepts)
READ_MODES = {
    "--grade-existing": (REGRADE, PAID, ("--batch-stamp", "--write-back", "--only-failed",
                                         "--min-answered", "--delay")),
    "--grade-category": (CATEGORY, COUNTS_FIRST, ("--batch-stamp", "--write-back",
                                                  "--concurrency")),
    "--grade-escalation": (GRADER, COUNTS_FIRST, ("--batch-stamp", "--write-back")),
    "--grade-suspicion": (CATEGORY, COUNTS_FIRST, ("--batch-stamp", "--write-back",
                                                   "--concurrency")),
    "--self-grade-kind": (None, PAID, ("--batch-stamp", "--write-back", "--delay")),
    "--reclassify": (REGRADE, PAID, ("--batch-stamp", "--write-back")),
    "--reinterrogate": (REGRADE, PAID, ("--batch-stamp", "--write-back",
                                        "--interrogation")),
    "--complete-pending": (GRADER, PAID, ("--batch-stamp", "--write-back")),
    "--resummarise": (None, FREE, ("--batch-stamp", "--write-back")),
    "--summarise-arms": (None, FREE, ()),
    "--compare": (None, FREE, ()),
}

COST_NOTE = {
    FREE: "Calls no API.",
    PAID: "Calls a model for every episode it selects.",
    COUNTS_FIRST: "Without write-back it only counts the calls; with it, it grades "
                  "and saves, and a stopped pass resumes.",
}


def _actions() -> dict:
    return {a.option_strings[0]: a for a in build_parser()._actions if a.option_strings}


def _help(action) -> str:
    text = " ".join((action.help or "").split())
    return text.removeprefix("Don't run the eval. ").removeprefix("Instead ")


def read_modes() -> list:
    """Every read mode the form offers, with what it takes, in the table's order."""
    actions = _actions()
    return [{"flag": flag, "help": _help(actions[flag]), "cost": cost,
             "cost_note": COST_NOTE[cost], "grader_flag": grader,
             "grader_default": actions[grader].default if grader else None,
             "choices": list(actions[flag].choices or []), "extras": list(extras)}
            for flag, (grader, cost, extras) in READ_MODES.items()]


def _mode_tokens(flag, spec, errors) -> list:
    if flag == "--compare":
        stamps = [str(s).strip() for s in spec.get("compare") or [] if str(s).strip()]
        if len(stamps) != 2:
            errors.append("Give the two batch stamps to compare.")
        return [flag, *stamps]
    choices = _actions()[flag].choices
    if choices:
        question = spec.get("question") or ""
        if question not in choices:
            errors.append(f"Choose which question {flag} asks: {', '.join(choices)}.")
        return [flag, question]
    return [flag]


def _grader_tokens(flag, spec, errors) -> list:
    grader, _cost, _extras = READ_MODES[flag]
    value = (spec.get("grader") or "").strip()
    if not grader or not value or value == _actions()[grader].default:
        return []
    if " " in value:
        errors.append("Give one grader model ID, with no spaces.")
    if flag == "--reinterrogate" and value == "all":
        errors.append("--reinterrogate takes one grader: that grader's verdicts decide "
                      "where each new ladder of questions stops.")
    return [grader, value]


def _extra_tokens(flag, spec, errors) -> list:
    allowed, given = READ_MODES[flag][2], spec.get("extras") or {}
    tokens = []
    for extra, value in given.items():
        if extra not in allowed:
            errors.append(f"{extra} does not apply to {flag}.")
        elif extra == "--write-back":
            continue
        elif value is True:
            tokens.append(extra)
        elif value not in (None, False, "") and str(value).strip():
            tokens += [extra, str(value).strip()]
    if "--min-answered" in given and str(given["--min-answered"]).strip() in ("0",):
        errors.append("--min-answered must be at least 1.")
    return tokens


def build_read(spec: dict, bundle_path: str = None) -> dict:
    """The read-mode command for a filled-in form, with its errors and warnings.

    `dry_run` is the same command without --write-back for a mode that, without
    it, only counts the calls it would make, so it spends nothing.
    """
    flag = spec.get("read_mode")
    errors, warnings = [], []
    if flag not in READ_MODES:
        return {"command": None, "dry_run": None, "errors": ["Choose a read mode."],
                "warnings": []}
    model = (spec.get("model") or "").strip()
    if not model or " " in model:
        errors.append("Give one model ID, with no spaces.")
    if not (spec.get("output_dir") or "").strip():
        errors.append("Give the output directory the runs are in.")
    tokens = ["python3", "-m", "subversionbench.run_eval", "--model", model]
    tokens += _mode_tokens(flag, spec, errors)
    if flag not in ("--compare", "--summarise-arms") and spec.get("nudge"):
        tokens += ["--nudge", spec["nudge"]]
    if spec.get("effort"):
        tokens += ["--effort", spec["effort"]]
    tokens += ["--output-dir", (spec.get("output_dir") or "").strip()]
    tokens += _grader_tokens(flag, spec, errors) + _extra_tokens(flag, spec, errors)
    write_back = bool((spec.get("extras") or {}).get("--write-back"))
    if "--write-back" in READ_MODES[flag][2] and not write_back:
        warnings.append("Without write-back the run files are left as they are.")
    prefix = [f"SUBVERSIONBENCH_SCENARIO_BUNDLE={bundle_path}"] if bundle_path else []
    line = " ".join(shlex.quote(t) for t in prefix + tokens)
    counts_first = READ_MODES[flag][1] == COUNTS_FIRST
    return {"command": None if errors else line + (" --write-back" if write_back else ""),
            "dry_run": line if counts_first and write_back and not errors else None,
            "errors": errors, "warnings": warnings}
