"""
One read mode per invocation.

_run_read_mode runs the first mode it reaches and returns, so a second mode
named alongside it was skipped and the command still exited 0:
`--resummarise --complete-pending` rebuilt summaries and asked nothing, and
the operator believed the pending interrogations were done.
"""

import contextlib
import io

import subversionbench.run_eval as ev_run


def _refused(argv) -> bool:
    parser = ev_run.build_parser()
    args = parser.parse_args(argv)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            ev_run._reject_contradictory_flags(parser, args)
    except SystemExit:
        return True
    return False


class TestOneReadModeAtATime:

    def test_two_read_modes_are_refused(self):
        for pair in (["--resummarise", "--complete-pending"],
                     ["--resummarise", "--reclassify"],
                     ["--reinterrogate", "--grade-existing"],
                     ["--summarise-arms", "--resummarise"]):
            assert _refused(pair), pair

    def test_each_mode_alone_is_accepted(self):
        for mode in ("--resummarise", "--complete-pending", "--reclassify",
                     "--reinterrogate", "--grade-existing", "--summarise-arms"):
            assert not _refused([mode]), mode

    def test_write_back_names_every_mode_it_applies_to(self):
        """The message listed four of the six, so an operator reading it
        could not learn that --complete-pending takes it too."""
        parser = ev_run.build_parser()
        args = parser.parse_args(["--write-back"])
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                ev_run._reject_contradictory_flags(parser, args)
        except SystemExit:
            pass
        for flag in ev_run._PER_FILE_FLAGS:
            assert flag in err.getvalue(), flag
