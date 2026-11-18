"""
The monitoring scenario's command form: what it prints must be accepted by the
monitoring parser, and the builder's server must offer it as a scenario.
"""

import http.client
import json
import shlex
import threading
from http.server import ThreadingHTTPServer

from monitoring import command_form as form
from monitoring.__main__ import build_parser
from subversionbench import command_builder as cb
from subversionbench.command_builder_server import HOST, make_handler


def _spec(**over) -> dict:
    base = {"step": "sample", "output_dir": "out", "corpus_root": ".",
            "arms": list(form.describe()["arms"]), "seed": "0", "per_arm": "",
            "monitor": "claude-haiku-5-5", "provider": "",
            "views": list(form.describe()["views"]), "cuts": list(form.describe()["cuts"]),
            "concurrency": "4", "limit": "", "send": False, "exact_matches": False}
    return {**base, **over}


def _parsed(command: str):
    tokens = shlex.split(command)
    assert tokens[:3] == ["python3", "-m", "monitoring"]
    return build_parser().parse_args(tokens[3:])


def test_each_step_is_accepted_by_the_monitoring_parser():
    sample = _parsed(form.build(_spec(arms=["mainline-r10"], seed="7", per_arm="5"))["command"])
    assert (sample.command, sample.arms, sample.seed, sample.per_arm) == (
        "sample", ("mainline-r10",), 7, 5)
    run = _parsed(form.build(_spec(step="run", views=["actions"], cuts=["end", "act"],
                                   concurrency="2", limit="10"))["command"])
    assert (run.command, run.monitor, run.views, run.cuts, run.concurrency, run.limit) == (
        "run", "claude-haiku-5-5", ("actions",), ("end", "act"), 2, 10)
    assert _parsed(form.build(_spec(step="report", exact_matches=True))["command"]).exact_matches


def test_a_run_is_a_dry_run_until_the_form_says_send():
    dry = form.build(_spec(step="run"))
    assert _parsed(dry["command"]).dry_run and not _parsed(dry["command"]).yes
    assert dry["dry_run"] is None
    sent = form.build(_spec(step="run", send=True))
    assert _parsed(sent["command"]).yes
    assert _parsed(sent["dry_run"]).dry_run


def test_an_unlisted_monitor_needs_a_provider_and_bad_values_are_refused():
    assert form.build(_spec(step="run", monitor="vendor/unlisted"))["command"] is None
    pinned = form.build(_spec(step="run", monitor="vendor/unlisted", provider="Somebody"))
    assert _parsed(pinned["command"]).openrouter_provider == "Somebody"
    for bad in ({"views": []}, {"cuts": ["nowhere"]}, {"concurrency": "0"},
                {"limit": "-1"}, {"monitor": ""}):
        assert form.build(_spec(step="run", **bad))["command"] is None
    assert form.build(_spec(arms=["no-such-arm"]))["command"] is None
    assert form.build(_spec(output_dir=" "))["command"] is None


def test_the_form_offers_every_arm_and_monitor_the_command_knows():
    from monitoring.arms import SOURCE_ARMS
    from monitoring.monitors import MONITORS
    described = form.describe()
    assert described["arms"] == [a.name for a in SOURCE_ARMS]
    assert [m["name"] for m in described["monitors"]] == list(MONITORS)


def _server():
    server = ThreadingHTTPServer((HOST, 0), make_handler([], (form,)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _call(server, method, path, body=None):
    conn = http.client.HTTPConnection(HOST, server.server_address[1], timeout=5)
    headers = {"Content-Type": "application/json"} if body else {}
    conn.request(method, path, body=body, headers=headers)
    return json.loads(conn.getresponse().read())


def test_the_server_offers_the_monitoring_scenario_and_builds_its_command():
    server = _server()
    try:
        offered = _call(server, "GET", "/api/options")["scenarios"]
        monitoring = [s for s in offered if s["id"] == form.SCENARIO_ID]
        assert len(monitoring) == 1 and monitoring[0]["form"]["steps"] == list(form.STEPS)
        result = _call(server, "POST", "/api/command",
                       json.dumps({**_spec(step="report"), "scenario": form.SCENARIO_ID}))
        assert result["command"].startswith("python3 -m monitoring ")
    finally:
        server.shutdown()
        server.server_close()


def test_blank_and_malformed_numbers_are_handled_as_the_command_would():
    assert form.build(_spec(seed="x"))["command"] is None
    assert form.build(_spec(seed=""))["command"] is not None
    assert form.build(_spec(step="run", concurrency=""))["command"] is None
    assert form.build(_spec(step="run", limit=""))["command"] is not None


def test_a_corpus_root_is_passed_only_when_it_is_not_the_default():
    assert "--corpus-root" not in form.build(_spec())["command"]
    moved = form.build(_spec(corpus_root="/data/corpora"))["command"]
    assert _parsed(moved).corpus_root == "/data/corpora"
    assert _parsed(form.build(_spec(step="nonsense"))["command"]).command == "sample"


def test_a_builder_without_the_extension_does_not_know_the_scenario():
    assert all(s["id"] != form.SCENARIO_ID for s in cb.options()["scenarios"])
    assert cb.build({"scenario": form.SCENARIO_ID})["errors"] == ["Unknown scenario."]
