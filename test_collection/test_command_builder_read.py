"""
The read-mode half of the run-command builder: grading and re-reading saved runs.

Every command it prints is put through run_eval's own refusals, not compared with
a string: those refusals are what decide which flag a mode accepts, so a command
that passes them is one run_eval would run. And the modes it offers are checked
against run_eval's own list of read modes, so a mode added there and not here fails.
"""

import argparse
import shlex

from subversionbench import command_builder as cb
from subversionbench import command_builder_read as cbr
from subversionbench import run_eval
from subversionbench.cli_parser import build_parser

FILLED = {"--batch-stamp": "20261120T174927", "--write-back": True,
          "--only-failed": True, "--min-answered": "3", "--delay": "2",
          "--concurrency": "4", "--interrogation": "partevidence"}


class _Refused(Exception):
    pass


class _Parser:
    def error(self, message):
        raise _Refused(message)


def _form(flag, **over) -> dict:
    mode = next((m for m in cbr.read_modes() if m["flag"] == flag),
                {"choices": [], "extras": []})
    form = {"mode": "read", "scenario": "", "model": "vendor/model", "read_mode": flag,
            "nudge": "none", "output_dir": "./out", "grader": "",
            "question": (mode["choices"] or [""])[0],
            "compare": ["20261120T174927", "20261120T215150"],
            "extras": {e: FILLED[e] for e in mode["extras"]}}
    return {**form, **over}


def _accepted_by_run_eval(command: str):
    """Parse the printed command and run it through run_eval's refusals."""
    tokens = shlex.split(command)
    args = build_parser().parse_args(tokens[tokens.index("--model"):])
    checked = argparse.Namespace(**vars(args),
                                 interrogations=run_eval.parse_interrogations(args.interrogation))
    run_eval._reject_contradictory_flags(_Parser(), checked)
    return checked


def test_the_form_offers_every_read_mode_run_eval_has_and_no_other():
    offered = {m["flag"] for m in cbr.read_modes()}
    assert offered == set(run_eval._PER_FILE_FLAGS) | {"--compare", "--summarise-arms"}


def test_every_mode_with_every_extra_filled_is_a_command_run_eval_accepts():
    for mode in cbr.read_modes():
        result = cb.build(_form(mode["flag"]))
        assert result["errors"] == [], mode["flag"]
        args = _accepted_by_run_eval(result["command"])
        assert run_eval._read_modes_chosen(args) == [mode["flag"]], mode["flag"]


def test_an_extra_the_mode_does_not_take_is_refused_as_run_eval_would():
    form = _form("--grade-category", extras={"--only-failed": True})
    assert cb.build(form)["errors"] == ["--only-failed does not apply to --grade-category."]
    tokens = shlex.split(cb.build(_form("--grade-category"))["command"]) + ["--only-failed"]
    try:
        _accepted_by_run_eval(" ".join(tokens))
    except _Refused:
        return
    raise AssertionError("run_eval accepted the flag the form refuses")


def test_each_mode_names_its_grader_with_the_flag_that_mode_reads():
    for flag, grader in (("--grade-existing", "--regrade"), ("--reclassify", "--regrade"),
                         ("--grade-category", "--category-grader"),
                         ("--grade-escalation", "--grader-model")):
        command = cb.build(_form(flag, grader="other/grader"))["command"]
        assert f"{grader} other/grader" in command, flag
        _accepted_by_run_eval(command)
    assert "--regrade" not in cb.build(_form("--grade-existing", grader="default"))["command"]


def test_reinterrogate_with_every_grader_is_refused():
    assert cb.build(_form("--reinterrogate", grader="all"))["errors"]


def test_a_mode_that_counts_first_offers_the_count_as_its_dry_run():
    result = cb.build(_form("--grade-category"))
    assert result["command"].endswith(" --write-back")
    assert result["dry_run"] == result["command"].removesuffix(" --write-back")
    assert cb.build(_form("--grade-existing"))["dry_run"] is None


def test_without_write_back_the_form_says_the_run_files_are_left_alone():
    result = cb.build(_form("--grade-existing", extras={"--write-back": False}))
    assert "--write-back" not in result["command"]
    assert result["warnings"] == ["Without write-back the run files are left as they are."]


def test_a_bundle_scenario_selects_its_bundle_for_the_read_too():
    scenario = next(s for s in cb.scenarios() if s["path"])
    command = cb.build(_form("--resummarise", scenario=scenario["id"]))["command"]
    assert command.startswith(f"SUBVERSIONBENCH_SCENARIO_BUNDLE={scenario['path']} ")


def test_malformed_read_forms_are_refused_not_assembled():
    for form, error in ((_form("--nope"), "Choose a read mode."),
                        (_form("--compare", compare=["one", ""]),
                         "Give the two batch stamps to compare."),
                        (_form("--grade-suspicion", question=""),
                         "Choose which question --grade-suspicion asks: decision, framing."),
                        (_form("--resummarise", model=""), "Give one model ID, with no spaces."),
                        (_form("--resummarise", output_dir=" "),
                         "Give the output directory the runs are in."),
                        (_form("--grade-existing", extras={"--min-answered": "0"}),
                         "--min-answered must be at least 1."),
                        (_form("--grade-existing", grader="two words"),
                         "Give one grader model ID, with no spaces."),
                        (_form("--resummarise", scenario="nope"), "Unknown scenario.")):
        result = cb.build(form)
        assert result["command"] is None and error in result["errors"], error


def test_the_options_carry_each_mode_s_help_from_the_parser():
    modes = cb.options()["read_modes"]
    existing = next(m for m in modes if m["flag"] == "--grade-existing")
    assert existing["help"].startswith("re-run the eval awareness grader")
    assert existing["grader_default"] == build_parser().get_default("regrade")
