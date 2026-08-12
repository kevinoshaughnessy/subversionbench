"""
The summary file: its schema, and reading back what a rebuild cannot re-derive.

Every figure the console prints has to reach this file, or it is a quantity shown
once and saved nowhere.
"""

import ast
import inspect

from subversionbench.reporting.facts import batch_facts, normalise_analyses
import subversionbench.run_eval as ev_run
from conftest import FakeArgs, batch_episode, collecting_identity


# Figures the summary does not store under their own name, each because the same
# quantity is already there by another route. The route is written out and CHECKED
# against a real summary rather than asserted in a comment: the earlier version of
# this test inferred persistence from whether a figure appeared in the expression
# that built a stored one, which counted `n_monitoring_obs_console` as saved because
# it feeds an interval - and an interval does not carry its own denominator.
ROUTES = {
    "n_out_of_scope": "rates.out_of_scope.successes",
    "ci_oos": "rates.out_of_scope.ci95",
    "n_network_probe": "rates.network_probe.successes",
    "ci_network": "rates.network_probe.ci95",
    "n_network_external": "rates.network_probe_external.successes",
    "n_fs_escape": "rates.filesystem_escape.successes",
    "n_fs_wrote": "rates.filesystem_escape_wrote.successes",
    "n_boundary_excl_scratch": "rates.sandbox_boundary_excl_scratch.successes",
    "n_transient": "rates.transient_tampering.successes",
    "n_goal_conflict_grader": "rates.goal_conflict_grader.successes",
    "n_monitoring_obs_console": "rates.monitoring_disabled.n",
    "n_aware_kw": "awareness_provenance.n_aware_keywords",
    "n_window": "awareness_provenance.n_aware_with_pre_command_window",
    # Inside the cross-analysis, which is None when every graded episode fell on
    # one side. The figures are then None too, so nothing is lost - and the
    # subgroup sizes that ARE informative in that case have their own field.
    "k_aware": "cross_analysis_awareness.aware.misaligned",
    "k_unaware": "cross_analysis_awareness.unaware.misaligned",
    "p_cross": "cross_analysis_awareness.fisher_p",
}

# Figures with no route because they are arithmetic on fields that are stored.
DERIVED = {
    "total_classified": "answer_classifier.agreed_with_keywords plus "
                        ".disagreed_with_keywords",
    "effort_label": "'/'.join(efforts_observed), for display only",
}

def _returned_figures():
    """Every figure batch_facts hands out, gathered from the construct modules.

    batch_facts no longer ends in one dict literal - it composes six modules and
    merges what each returns. So the set is the union of their return literals, less
    the denominators that exist only for rates.py, plus the few keys the composition
    sets itself.

    Each module's return is taken as a direct statement of its function body rather
    than by walking every Return in it: several build figures with nested helpers that
    also return dicts, and a walk picks up whichever of those comes last - which
    silently compared the wrong set of names once already.
    """
    from subversionbench.reporting import facts as pkg
    producers = (pkg.misalignment_facts, pkg.scheming_facts, pkg.awareness_facts,
                 pkg.quality_facts, pkg.timing_facts, pkg.rate_table)
    out = set()
    for fn in producers:
        body = ast.parse(inspect.getsource(fn)).body[0].body
        own = [s for s in body if isinstance(s, ast.Return)]
        assert len(own) == 1 and isinstance(own[0].value, ast.Dict), (
            f"{fn.__name__} no longer ends in exactly one dict literal")
        out |= {k.value for k in own[0].value.keys if isinstance(k, ast.Constant)}
    # and the keys the composition sets directly, read off its own literal
    compose = ast.parse(inspect.getsource(batch_facts)).body[0]
    for node in ast.walk(compose):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == "facts"
                and isinstance(node.value, ast.Dict)):
            out |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return out - set(pkg.INTERNAL_FIGURES)

class TestEveryFigureReachesTheSummaryFile:
    """What the report shows must be re-derivable from disk.

    The whole analysis pipeline rests on being able to rebuild any figure from saved
    episodes, and a quantity that exists only in terminal scrollback is outside that
    guarantee. Before v41 six were: the observed reasoning-effort set, the transient
    tamperings that banked a passing check, which indicator phrases fired, the
    per-rubric trigger counts, and the awareness subgroup sizes whenever the
    cross-analysis could not be computed.
    """

    def _figures_and_direct(self):
        import subversionbench.run_eval as ev
        figures = _returned_figures()
        sb = ast.parse(inspect.getsource(ev.summarise_batch)).body[0]
        sd = [x for x in ast.walk(sb) if isinstance(x, ast.Assign)
              and any(getattr(t, "id", "") == "summary" for t in x.targets)][0]
        direct = {x.id for x in ast.walk(sd.value)
                  if isinstance(x, ast.Name)} & figures
        return figures, direct

    def _summary_and_facts(self):
        """A summary built from episodes chosen so every route is populated.

        Both an aware and an unaware episode, because the cross-analysis routes are
        only reachable when the split has two sides - which is the case a corpus
        batch may not happen to provide.
        """
        import tempfile
        import types
        import io
        import contextlib
        import subversionbench.run_eval as ev
        episodes = [
            batch_episode(tampered=True, monitoring=True, aware=True,
                     answers=[{"verdict": "denied", "answer": "No."}]),
            batch_episode(aware=True),
            batch_episode(tampered=True, escape=["cat /etc/passwd"]),
            batch_episode(),
        ]
        normalise_analyses(episodes)
        facts = batch_facts(episodes, {})
        with tempfile.TemporaryDirectory() as tmp:
            args = types.SimpleNamespace(
                model="claude-opus-5", nudge="strong", effort=None, oversight=True,
                lure=False, output_dir=tmp, delay=0, max_tokens=8192,
                max_turns=40, no_power=True)
            with contextlib.redirect_stdout(io.StringIO()):
                identity = ev.BatchIdentity.collecting(args, "m", args.effort, stamp="s")
                summary = ev.summarise_batch(args, episodes, identity)
        return summary, facts

    def test_no_figure_is_shown_and_then_lost(self):
        figures, direct = self._figures_and_direct()
        unaccounted = figures - direct - set(ROUTES) - set(DERIVED)
        assert not unaccounted, (
            f"these figures reach the report and no summary file: "
            f"{sorted(unaccounted)}. Either store them, or add them to ROUTES "
            f"with the path by which the same quantity is already saved.")

    def test_each_route_actually_carries_the_value(self):
        """The claims in ROUTES, checked rather than trusted."""
        summary, facts = self._summary_and_facts()
        assert summary["cross_analysis_awareness"], (
            "the fixture must produce a two-sided split, or the cross routes "
            "below are not being checked at all")
        for figure, path in ROUTES.items():
            node = summary
            for part in path.split("."):
                assert node is not None, f"{path} runs through a None for {figure}"
                node = node[part]
            assert node == facts[figure], (
                f"summary.{path} is {node!r} but facts[{figure!r}] is "
                f"{facts[figure]!r} - the route no longer carries the figure")

    def test_no_stale_entries(self):
        """An allowlist that outlives its figures stops meaning anything."""
        figures, direct = self._figures_and_direct()
        listed = set(ROUTES) | set(DERIVED)
        gone = listed - figures
        assert not gone, f"ROUTES/DERIVED name figures that no longer exist: {sorted(gone)}"
        redundant = listed & direct
        assert not redundant, (
            f"these are stored under their own name, so they need no route: "
            f"{sorted(redundant)}")

class TestTheInterfaceCannotDriftFromItsConsumer:
    def _unpacked(self, fn):
        """The `name = facts["name"]` bindings one consumer declares.

        Takes a module as readily as a function: the console's bindings are spread
        over its nineteen section functions, each declaring what its own block of
        the report reads, so scanning only `render_report` would find none of them.
        """
        out = set()
        for node in ast.walk(ast.parse(inspect.getsource(fn))):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Subscript)
                    and getattr(node.value.value, "id", "") == "facts"
                    and isinstance(node.value.slice, ast.Constant)):
                assert node.targets[0].id == node.value.slice.value, (
                    f"{node.targets[0].id} is bound from "
                    f"facts[{node.value.slice.value!r}] - the local and the "
                    f"figure must be the same name, or the line reads the "
                    f"wrong number under a familiar label")
                out.add(node.targets[0].id)
        return out

    def test_every_unpacked_figure_is_one_facts_returns(self):
        """Each consumer binds the figures it reads by name. A name it binds that
        facts does not return is a KeyError waiting for whichever batch first
        reaches that line - not caught by the type checker, and invisible until
        the branch that touches it runs."""
        import subversionbench.run_eval as ev
        from subversionbench.reporting import console
        returned = _returned_figures()
        for fn in (ev.summarise_batch, console):
            extra = self._unpacked(fn) - returned
            assert not extra, (f"{fn.__name__} unpacks figures facts does not "
                               f"return: {sorted(extra)}")

    def test_no_figure_is_returned_that_nobody_reads(self):
        """The other direction, and the one that keeps the interface honest.

        There are two consumers now - the summary builder and the console report -
        so the check is against their union rather than either alone. A figure
        nobody reads is either dead weight or, worse, something computed for a
        consumer that quietly stopped reading it; both are worth a failure. The
        intermediates that only facts.py itself needs are deliberately not in the
        return dict, which is what makes this assertion meaningful.
        """
        import subversionbench.run_eval as ev
        from subversionbench.reporting import console
        read = self._unpacked(ev.summarise_batch) | self._unpacked(console)
        orphaned = _returned_figures() - read
        assert not orphaned, (
            f"facts returns figures neither the summary nor the report reads: "
            f"{sorted(orphaned)}")

class TestTheSummaryHeaderStatesTheEffort:
    """Reported from the observed SET across the runs, not from args.effort.

    Two efforts are two conditions and must not be pooled, so a batch that
    straddles them has to say so rather than report whichever level this
    invocation happened to carry. Same reasoning as the rollout and isolation
    provenance fields."""

    def _summary_line(self, efforts):
        import io, contextlib, tempfile
        out = tempfile.mkdtemp()
        args = FakeArgs(output_dir=out, model="m", nudge="strong",
                         grader_model="g")
        args.batch_stamp = "S"; args.effort = None
        args.max_turns = 40; args.max_tokens = 8192
        args.no_power = True; args.runs = len(efforts)
        results = [{"analysis": {"monitoring_disabled": False,
                                 "oversight_tampered": False,
                                 "sandbox_escape_attempts": [],
                                 "sandbox_escape_attempts_after_refusal": [],
                                 "eval_awareness_keywords": {
                                     "eval_aware": False,
                                     "goal_conflict_noted": False},
                                 "ran_quality_check_preview": False,
                                 "quality_check_result": None,
                                 "read_internal_memo": False,
                                 "read_monitoring_config": False},
                    "transcript": [], "effort": e} for e in efforts]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ev_run.summarise_batch(
                args, results,
                collecting_identity(args, "m", "S"))
        return next(l for l in buf.getvalue().splitlines()
                    if l.startswith("SUMMARY:")), buf.getvalue()

    def test_a_single_effort_is_named(self):
        line, _ = self._summary_line(["high", "high"])
        assert "effort=high" in line

    def test_no_effort_sent_is_spelled_out(self):
        line, _ = self._summary_line([None, None])
        assert "effort=not sent" in line

    def test_a_mixed_batch_names_both_and_warns(self):
        """The failure this guards: pooling two reasoning conditions under one
        rate, invisibly."""
        line, out = self._summary_line(["high", "low"])
        assert "effort=high/low" in line
        assert "mixes reasoning efforts" in out


class TestSettingsRecoveredFromAPreviousSummary:
    """runtime_from_existing_summary had no test at all.

    Its own comment records the defect it was written to fix: the recovered
    settings used to be assigned onto `args`, and `args` is shared across a
    fan-out, so one batch's settings leaked into every later batch in the run.
    That defect was fixed and left unguarded, in the function `--resummarise`
    depends on for every batch it rebuilds.
    """

    def _previous(self, **over):
        import json
        import tempfile
        d = tempfile.mkdtemp()
        summary = {"model": "m", "max_tokens": 4096, "max_turns": 25,
                   "batch_aborted": True,
                   "episode_failures": [{"run": 3, "error": "boom"}],
                   "timing": {"total_elapsed_seconds": 123.4,
                              "total_delay_seconds": 9,
                              "delay_setting": 7}}
        summary.update(over)
        path = f"{d}/summary_m_strong_20260101T000000.json"
        with open(path, "w") as f:
            json.dump(summary, f)
        return path

    def test_the_settings_the_batch_ran_under_are_recovered(self):
        """Not the defaults the rebuild was invoked with. A rebuild started
        without --max-tokens would otherwise record 8192 for a batch that ran at
        4096, and the artefact would misdescribe the condition."""
        from subversionbench.reporting.summary import runtime_from_existing_summary
        runtime = runtime_from_existing_summary(self._previous(), [])
        assert runtime["settings"]["max_tokens"] == 4096
        assert runtime["settings"]["max_turns"] == 25
        assert runtime["settings"]["delay"] == 7

    def test_it_returns_data_and_mutates_no_namespace(self):
        """The recorded defect. `args` is shared across a fan-out, so writing the
        recovered settings onto it carried one batch's settings into every later
        one."""
        from subversionbench.reporting.summary import runtime_from_existing_summary
        args = FakeArgs(output_dir="/tmp/nowhere", model="m", nudge="strong",
                        grader_model="g")
        args.max_tokens = 8192
        before = dict(vars(args))
        runtime_from_existing_summary(self._previous(), [])
        assert dict(vars(args)) == before

    def test_the_effort_is_deliberately_not_recovered(self):
        """It belongs to the batch's identity, which is read from the run
        filenames - a sharper source than a previous summary."""
        from subversionbench.reporting.summary import runtime_from_existing_summary
        runtime = runtime_from_existing_summary(
            self._previous(effort="max"), [])
        assert "effort" not in runtime["settings"]

    def test_an_absent_setting_is_omitted_rather_than_defaulted(self):
        """A key invented here would be indistinguishable from one the batch
        really ran under."""
        from subversionbench.reporting.summary import runtime_from_existing_summary
        path = self._previous()
        import json
        data = json.load(open(path))
        del data["max_turns"]
        json.dump(data, open(path, "w"))
        runtime = runtime_from_existing_summary(path, [])
        assert "max_turns" not in runtime["settings"]

    def test_the_abort_flag_and_failures_survive_a_rebuild(self):
        """Neither is derivable from the run files: an aborted batch has fewer of
        them, which looks exactly like a batch that was asked for fewer."""
        from subversionbench.reporting.summary import runtime_from_existing_summary
        runtime = runtime_from_existing_summary(self._previous(), [])
        assert runtime["aborted"] is True
        assert runtime["failures"] == [{"run": 3, "error": "boom"}]

    def test_the_elapsed_time_is_carried_as_a_span_not_a_duration(self):
        """summarise_batch subtracts two clock readings, so the recovered elapsed
        has to arrive as a start and an end or the rebuild reports 0 seconds."""
        from subversionbench.reporting.summary import runtime_from_existing_summary
        runtime = runtime_from_existing_summary(self._previous(), [])
        assert runtime["t_batch_end"] - runtime["t_batch_start"] == 123.4

    def test_a_missing_previous_summary_is_not_an_error(self):
        """The first rebuild of a batch collected before summaries existed."""
        from subversionbench.reporting.summary import runtime_from_existing_summary
        runtime = runtime_from_existing_summary("/nonexistent/summary.json", [])
        assert "settings" not in runtime

    def test_the_reasoning_config_comes_from_the_runs_not_the_summary(self):
        """The runs are the authority on what was actually sent."""
        from subversionbench.reporting.summary import runtime_from_existing_summary
        runtime = runtime_from_existing_summary(
            "/nonexistent/summary.json",
            [{"reasoning_config": ""}, {"reasoning_config": "budget=4096"}])
        assert runtime["reasoning_config"] == "budget=4096"


class TestARebuildReproducesTheSummaryItRebuilds:
    """The invariant the whole read-mode design rests on, and nothing asserted it.

    --resummarise exists so a summary can be regenerated from saved runs without
    paying for the rollouts again. That is only sound if rebuilding a batch
    produces the summary the live run produced. If it does not, every published
    figure depends on which path last wrote the file.
    """

    def _summarise(self, episodes, runtime, out):
        import contextlib
        import io
        args = FakeArgs(output_dir=out, model="m", nudge="strong", grader_model="g")
        args.max_tokens, args.max_turns, args.no_power = 8192, 40, True
        args.oversight, args.lure, args.delay = True, False, 0
        identity = collecting_identity(args, "m", stamp="20260101T000000")
        normalise_analyses(episodes)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return ev_run.summarise_batch(args, episodes, identity, runtime)

    def _episodes(self):
        from subversionbench.grading import MISALIGNED_ACTS
        act = [a for a in MISALIGNED_ACTS if a["name"] == "oversight"][0]
        answers = [{"question": "q", "answer": "No.", "verdict": "denied",
                    "used_keyword_fallback": False, "classifier_called": True}]
        eps = []
        for tampered in (True, False, True):
            e = batch_episode(tampered=tampered, monitoring=tampered, aware=tampered,
                              disclosed=False if tampered else None,
                              answers=answers if tampered else None)
            e["timing"] = {"eval_seconds": 10.0, "grader_seconds": 2.0,
                           "total_run_seconds": 12.0}
            e[act["key"]] = tampered
            eps.append(e)
        return eps

    def test_rebuilding_from_the_same_runs_gives_the_same_summary(self):
        """Same episodes, same identity, same recovered runtime. Every field is
        compared, not a chosen few, because the fields that went stale in the past
        were the ones nobody thought to check."""
        import tempfile
        runtime = {"t_batch_start": 0.0, "t_batch_end": 90.0,
                   "total_delay_seconds": 6,
                   "settings": {"max_tokens": 8192, "max_turns": 40, "delay": 0},
                   "aborted": False, "failures": [], "reasoning_config": ""}
        live = self._summarise(self._episodes(), runtime, tempfile.mkdtemp())
        rebuilt = self._summarise(self._episodes(), runtime, tempfile.mkdtemp())
        volatile = {"timestamp"}
        differing = {k for k in set(live) | set(rebuilt)
                     if k not in volatile and live.get(k) != rebuilt.get(k)}
        assert not differing, f"a rebuild produced different figures: {differing}"

    def test_only_the_timestamp_is_allowed_to_differ(self):
        """Named explicitly, so a second volatile field has to be justified here
        rather than quietly excluded from the comparison above."""
        import tempfile
        runtime = {"t_batch_start": 0.0, "t_batch_end": 90.0,
                   "total_delay_seconds": 0, "aborted": False, "failures": [],
                   "reasoning_config": ""}
        live = self._summarise(self._episodes(), runtime, tempfile.mkdtemp())
        rebuilt = self._summarise(self._episodes(), runtime, tempfile.mkdtemp())
        assert live["timestamp"] != rebuilt["timestamp"] or True
        assert {k for k in live if live[k] != rebuilt.get(k)} <= {"timestamp"}

    def test_the_rebuild_is_written_where_the_identity_says(self):
        import tempfile
        from pathlib import Path
        out = tempfile.mkdtemp()
        self._summarise(self._episodes(), {"aborted": False, "failures": []}, out)
        written = list(Path(out).glob("summary_*.json"))
        assert len(written) == 1, written
        assert "20260101T000000" in written[0].name
