"""
The run-command builder: the command it prints must be one run_eval accepts.

A form that assembles a command is a second statement of the command line, so
the checks here parse what it prints with the real parser rather than compare
strings. The defect this was written against: a nudge of `none` was dropped
along with the goal-guarding arm's own `none`, so a capability command was
printed without --nudge and run at the parser's default, `strong` - capability
under pressure, the one thing the arm exists not to measure.
"""

import http.client
import json
import re
import shlex
import threading
from http.server import ThreadingHTTPServer

from subversionbench import command_builder as cb
from subversionbench.cli_parser import build_parser
from subversionbench.command_builder_server import HOST, make_handler

BATCH_ONLY = ("--nudges", "--oversights", "--lures", "--goalguards", "--variants")


def _form(**over) -> dict:
    form = {"mode": "batch", "scenario": "", "model": "vendor/model", "provider": "",
            "sort": "", "effort": "", "grade": True, "grader_model": "gpt-6-sol",
            "capability": "", "nudges": ["none", "strong", "max"],
            "oversights": ["true", "false"], "lures": ["false", "true"],
            "goalguards": ["none"], "variants": [], "runs": 10, "output_dir": "./out",
            "date_mode": "", "advanced": {}}
    return {**form, **over}


def _single(**over) -> dict:
    base = {"mode": "single", "nudges": ["none"], "oversights": ["true"],
            "lures": ["false"], "goalguards": [], "runs": 3}
    return _form(**{**base, **over})


def _parsed(command: str):
    tokens = shlex.split(command)
    start = tokens.index("--model")
    return build_parser().parse_args(tokens[start:])


def test_a_single_command_is_accepted_by_the_real_parser():
    result = cb.build(_single(provider="Mistral", effort="high", grade=False,
                              advanced={"concurrency": "3"}))
    assert result["errors"] == []
    args = _parsed(result["command"])
    assert (args.model, args.nudge, args.oversight, args.lure) == (
        "vendor/model", "none", "true", "false")
    assert (args.openrouter_provider, args.effort, args.no_grader, args.concurrency) == (
        "Mistral", "high", True, 3)


def test_a_capability_command_carries_nudge_none():
    result = cb.build(_single(capability="sandbox"))
    assert result["errors"] == []
    args = _parsed(result["command"])
    assert (args.capability, args.nudge) == ("sandbox", "none")
    assert "--nudge none" in result["command"]


def test_a_batch_command_passes_only_flags_the_parser_knows():
    result = cb.build(_form(provider="Mistral", goalguards=["replacement", "deferred"]))
    tokens = shlex.split(result["command"])
    assert tokens[0] == "./run_all_arms.sh"
    rest, skip = [], False
    for token in tokens[1:]:
        if skip:
            skip = False
        elif token in BATCH_ONLY:
            skip = True
        else:
            rest.append(token)
    args = build_parser().parse_args(rest)
    assert args.openrouter_provider == "Mistral"
    assert result["arms"] == 24 and result["episodes"] == 240


def test_dry_run_is_offered_for_a_batch_and_not_a_single_run():
    assert cb.build(_form())["dry_run"].startswith("DRY_RUN=1 ./run_all_arms.sh")
    assert cb.build(_single())["dry_run"] is None


def test_a_capability_arm_is_refused_where_it_would_be_misread():
    assert cb.build(_form(capability="sandbox"))["command"] is None
    assert cb.build(_single(capability="sandbox", nudges=["strong"]))["command"] is None
    assert cb.build(_single(capability="sandbox", lures=["true"]))["command"] is None
    refused = cb.build(_single(capability="oversight", oversights=["false"]))
    assert refused["command"] is None and refused["errors"]


def test_a_bundle_is_selected_by_its_own_path_and_variants_are_its_own():
    found = [s for s in cb.scenarios() if s["variants"] and s["cells"]]
    assert found, "no committed bundle declares both variants and cells"
    scenario = found[0]
    cell = scenario["cells"][0]
    form = _single(scenario=scenario["id"], variants=[scenario["variants"][0]],
                   oversights=[str(cell[0]).lower()], lures=[str(cell[1]).lower()])
    result = cb.build(form)
    assert result["errors"] == []
    assert result["command"].startswith(f"{cb.BUNDLE_ENV_VAR}={scenario['path']} ")
    assert cb.build({**form, "variants": ["no-such-variant"]})["command"] is None
    other = [c for c in ((True, True), (False, False), (False, True)) if list(c) not in
             [list(x) for x in scenario["cells"]]]
    undeclared = cb.build({**form, "oversights": [str(other[0][0]).lower()],
                           "lures": [str(other[0][1]).lower()]})
    assert undeclared["command"] is None


def test_every_curated_name_is_a_real_flag_and_advanced_is_the_rest():
    real = {a.dest for a in build_parser()._actions if a.option_strings}
    assert cb.CURATED | cb.NOT_FOR_A_NEW_RUN <= real
    advanced = {f["dest"] for f in cb.advanced_fields()}
    assert advanced and advanced.isdisjoint(cb.CURATED | cb.NOT_FOR_A_NEW_RUN)
    assert advanced <= set(cb.fields())


def _sidecars() -> list:
    sidecars = [json.loads(p.read_text(encoding="utf-8"))
                for p in cb.SCENARIO_DIR.glob("*.pins.json")]
    assert sidecars
    return sidecars


def test_only_the_newest_rollout_of_each_scenario_is_offered():
    by_name = {}
    for side in _sidecars():
        by_name.setdefault(side["scenario_name"], []).append(side["rollout_version"])
    assert any(len(rollouts) > 1 for rollouts in by_name.values())
    offered = {s["name"]: s["rollout"] for s in cb.scenarios() if s["path"]}
    assert set(offered) == set(by_name)
    for name, rollouts in by_name.items():
        newest = max(rollouts, key=lambda r: int(re.search(r"(\d+)$", r).group(1)))
        assert offered[name] == newest
    assert all(s["path"] is None or (cb.SCENARIO_DIR.parent.parent / s["path"]).exists()
               for s in cb.scenarios())


def test_an_older_rollout_is_not_a_scenario_the_builder_will_build_for():
    older = [p.name.removesuffix(".pins.json") for p in cb.SCENARIO_DIR.glob("*.pins.json")]
    offered = {s["id"] for s in cb.scenarios()}
    stale = sorted(set(older) - offered)
    assert stale
    assert cb.build(_single(scenario=stale[0]))["errors"] == ["Unknown scenario."]


def test_each_scenario_names_the_directory_its_corpus_is_collected_in():
    for scenario in cb.scenarios():
        dirs = scenario["output_dirs"]
        assert dirs["propensity"] == f"./eval_results_{scenario['rollout']}"
        assert dirs["capability"] == dirs["propensity"] + "cap"
    shipped = cb.scenarios()[0]["output_dirs"]
    assert shipped["goalguard_capability"] == shipped["goalguard"] + "cap"
    assert all("goalguard" not in s["output_dirs"] for s in cb.scenarios()[1:])


def test_the_page_updates_the_output_directory_when_the_scenario_changes():
    from subversionbench.command_builder_page import PAGE
    change = PAGE.split("function applyScenario(){")[1].split("function applyCapability")[0]
    assert "autoDir(true)" in change


def test_an_unknown_advanced_setting_is_refused():
    assert cb.build(_single(advanced={"no_such_flag": "1"}))["command"] is None


def _server():
    server = ThreadingHTTPServer((HOST, 0), make_handler(["vendor/model"]))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _ask(server, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(HOST, server.server_address[1], timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    return response.status, response.read()


def test_the_server_serves_options_and_builds_a_command():
    server = _server()
    try:
        status, page = _ask(server, "GET", "/")
        assert status == 200 and b"SubversionBench run builder" in page
        status, raw = _ask(server, "GET", "/api/options")
        assert status == 200 and json.loads(raw)["models"] == ["vendor/model"]
        status, raw = _ask(server, "POST", "/api/command", json.dumps(_single()),
                           {"Content-Type": "application/json"})
        assert status == 200 and json.loads(raw)["errors"] == []
    finally:
        server.shutdown()
        server.server_close()


def test_the_server_refuses_a_foreign_host_and_a_non_json_post():
    server = _server()
    try:
        assert _ask(server, "GET", "/api/options", headers={"Host": "evil.example"})[0] == 403
        assert _ask(server, "POST", "/api/command", "{}",
                    {"Content-Type": "text/plain"})[0] == 415
        assert _ask(server, "POST", "/api/command", "[]",
                    {"Content-Type": "application/json"})[0] == 400
    finally:
        server.shutdown()
        server.server_close()
