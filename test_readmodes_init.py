"""
The read-only modes' shared surface, and how little of it there is.

Four modes that diverge on purpose. They share exactly one thing - which saved run
files am I working on - and past that each writes back under a policy protecting
something specific. A shared writer would need a policy flag per mode, which is
easier to get wrong in the direction that loses data.
"""

import importlib
import inspect

import subversionbench.readmodes as readmodes

MODES = ("grade_existing_runs", "reclassify_existing_runs",
         "reinterrogate_existing_runs", "resummarise_existing_runs")


class TestTheFourModesAreAllReachable:
    def test_each_mode_is_exported(self):
        for name in MODES:
            assert name in readmodes.__all__, name
            assert callable(getattr(readmodes, name))

    def test_every_exported_name_exists(self):
        for name in readmodes.__all__:
            assert hasattr(readmodes, name), name

    def test_all_is_sorted_and_unique(self):
        assert readmodes.__all__ == sorted(readmodes.__all__)
        assert len(readmodes.__all__) == len(set(readmodes.__all__))

    def test_they_all_take_the_same_two_arguments(self):
        """run_eval dispatches to them interchangeably, so a mode with a different
        signature would fail only on the branch that reaches it."""
        for name in MODES:
            params = list(inspect.signature(getattr(readmodes, name)).parameters)
            assert params[:2] == ["args", "model_slug"], (name, params)

    def test_they_all_return_an_exit_code(self):
        """main() returns whatever they return, so a mode returning None would
        exit 0 after refusing to do anything."""
        for name in MODES:
            src = inspect.getsource(getattr(readmodes, name))
            assert "return 0" in src or "return 1" in src or "return 2" in src, name


class TestOnlyTheSelectionIsShared:
    def test_the_one_shared_step_is_exported(self):
        assert "find_run_files_or_explain" in readmodes.__all__
        assert "fan_out_read_mode" in readmodes.__all__

    def test_every_mode_reaches_its_files_through_it(self):
        """Otherwise one mode explains an empty selection differently from the
        others, and the operator has to learn which."""
        for name in MODES:
            module = importlib.import_module(
                getattr(readmodes, name).__module__)
            src = inspect.getsource(module)
            assert "find_run_files_or_explain" in src, name

    def test_no_mode_imports_another(self):
        """The divergence is the design. A mode calling another would inherit its
        write-back policy, and the policies are not interchangeable."""
        owners = {name: getattr(readmodes, name).__module__ for name in MODES}
        for name, module_name in owners.items():
            src = inspect.getsource(importlib.import_module(module_name))
            for other, other_module in owners.items():
                if other == name:
                    continue
                leaf = other_module.rsplit(".", 1)[1]
                assert f"from .{leaf} import" not in src, (name, other)
                assert f"import {other_module}" not in src, (name, other)


class TestTheRederivedAllowlistIsPartOfTheSurface:
    def test_it_is_exported_from_here_not_from_one_mode(self):
        """--resummarise owns it, but --reclassify and the summary builder are
        judged against it, so it belongs to the package rather than to a mode."""
        assert "REDERIVED_ANALYSIS_FIELDS" in readmodes.__all__

    def test_it_is_immutable(self):
        """It decides what --write-back is permitted to save. A list here could be
        appended to at runtime by any caller."""
        assert isinstance(readmodes.REDERIVED_ANALYSIS_FIELDS, tuple)

    def test_it_holds_no_duplicates(self):
        fields = readmodes.REDERIVED_ANALYSIS_FIELDS
        assert len(fields) == len(set(fields))

    def test_it_names_no_sampled_field(self):
        """The split the whole read-mode design rests on: preserve what was
        sampled, re-derive what follows from it. An answer list or a grader reading
        in this allowlist would let a rebuild overwrite something paid for."""
        from subversionbench.grading import MISALIGNED_ACTS
        sampled = set()
        for act in MISALIGNED_ACTS:
            sampled |= {act["followup_key"], act["followup_key"] + "_by_variant",
                        act["disclosure_key"]}
        overlap = sampled & set(readmodes.REDERIVED_ANALYSIS_FIELDS)
        assert not overlap, f"a rebuild could overwrite sampled data: {overlap}"
