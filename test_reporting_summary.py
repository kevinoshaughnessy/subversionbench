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
