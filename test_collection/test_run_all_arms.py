"""
run_all_arms.sh: stopping the batch versus one arm failing.

The script runs 12 arms back to back and guards each with `if ! "${cmd[@]}"`, so
that a model having a rough patch on one arm does not end the eleven after it.
That guard is right, and it is also the thing an operator's stop request has to
get past.

WHY THESE ARE MEASURED AND NOT REASONED ABOUT
---------------------------------------------
Bash's behaviour here is not what it looks like. Before the trap existed:

  A real Ctrl-C already stopped the loop. It reaches the whole foreground
  process group, the arm dies, and bash's default action ends the script. This
  case was never broken - which is worth pinning, because a trap written
  carelessly could take a working path away.

  A signal to the SCRIPT ALONE was swallowed. The arm ran to completion, the
  guard read an ordinary non-zero exit, and the next arm started.

  SIGTERM ended the script mid-arm and said nothing about what had been
  collected or how to resume.

  A signal to the ARM ALONE is still absorbed, and no trap can change that:
  run_eval.py catches KeyboardInterrupt and returns 0 or 1 whether it was
  interrupted or merely failed, so the guard cannot tell the two apart. That
  limit is asserted below rather than left as a surprise, so the day someone
  gives run_eval.py a distinct exit code, the test that has to change says so.

Every test here runs the script under DRY_RUN=1, which spends nothing and calls
no API, and drives it by reading its output rather than by sleeping for a fixed
time - a wall-clock assertion would need tuning on one machine and would flake
on a slower one.
"""

import os
import shutil
import signal
import subprocess
import sys
import unittest

import conftest

SCRIPT = conftest.PROJECT_ROOT / "run_all_arms.sh"
# 2 oversight x 2 lure x 1 nudge = 4 arms, enough that an interrupt after the
# first has arms left to prove were not started.
ARGS = ["--model", "test/stub-model", "--runs", "1", "--nudges", "none"]
ARMS = 4


def _wait_for_first_arm(process) -> str:
    """Read until the script is demonstrably inside the arm loop.

    Event-driven on purpose. The alternative - sleep a bit, then signal - has to
    be tuned to one machine and flakes on a slower one, and this suite has been
    bitten by that before.
    """
    seen = []
    while True:
        line = process.stdout.readline()
        if not line:
            return "".join(seen)
        seen.append(line)
        if "would run:" in line:
            return "".join(seen)


def _run_and_signal(how: str) -> tuple:
    """Start the script in its own process group, signal it, return (rc, output).

    `start_new_session` matters: a background job of a NON-INTERACTIVE shell has
    SIGINT set to ignore, and bash cannot trap a signal it inherited as ignored.
    Signalling such a job measures nothing - the first version of this check
    reported that neither the old nor the new script stopped, because both had
    SIGINT disabled before they began.
    """
    env = dict(os.environ, DRY_RUN="1")
    process = subprocess.Popen(
        ["bash", str(SCRIPT), *ARGS], cwd=str(conftest.PROJECT_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True, env=env)
    try:
        early = _wait_for_first_arm(process)
        pgid = os.getpgid(process.pid)
        if how == "group-INT":
            os.killpg(pgid, signal.SIGINT)      # exactly what Ctrl-C sends
        elif how == "script-INT":
            os.kill(process.pid, signal.SIGINT)
        elif how == "script-TERM":
            os.kill(process.pid, signal.SIGTERM)
        else:
            raise AssertionError(how)
        rest, _ = process.communicate(timeout=60)
    except BaseException:
        process.kill()
        raise
    return process.returncode, early + (rest or "")


class TestAnOperatorStopEndsTheBatch(unittest.TestCase):
    """A stop request must not be absorbed by the one-bad-arm guard."""

    def test_a_signal_to_the_script_alone_stops_it(self):
        """The case that was broken. The arm loop used to carry on to the next
        arm, because the guard cannot tell a signal from a failed arm."""
        rc, out = _run_and_signal("script-INT")
        self.assertEqual(rc, 130, out)
        self.assertIn("Stopped by SIGINT", out)
        self.assertLess(out.count("would run:"), ARMS,
                        f"every arm still started, so the stop was absorbed:\n{out}")

    def test_a_real_ctrl_c_stops_it(self):
        """This case already worked, and is pinned so a future trap cannot take
        a working path away."""
        rc, out = _run_and_signal("group-INT")
        self.assertIn(rc, (130, -signal.SIGINT), out)
        self.assertLess(out.count("would run:"), ARMS, out)

    def test_sigterm_stops_it_and_says_how_to_resume(self):
        """SIGTERM used to end the script mid-arm with no word on what had been
        collected. The message matters: without it the next question is always
        whether the half-collected arm has to be thrown away."""
        rc, out = _run_and_signal("script-TERM")
        self.assertEqual(rc, 143, out)
        self.assertIn("Stopped by SIGTERM", out)
        self.assertIn("re-run this script with no", out)
        self.assertIn("--resume", out)

    def test_the_stop_message_does_not_claim_the_arm_finished(self):
        """A stop leaves one arm partly collected, and the resume path depends
        on the reader knowing that."""
        _, out = _run_and_signal("script-TERM")
        self.assertIn("was not completed", out)


class TestOneBadArmStillDoesNotEndTheBatch(unittest.TestCase):
    """The guard the trap must not have broken."""

    def test_all_arms_run_when_nothing_interrupts(self):
        env = dict(os.environ, DRY_RUN="1")
        done = subprocess.run(["bash", str(SCRIPT), *ARGS],
                              cwd=str(conftest.PROJECT_ROOT), env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stdout.count("would run:"), ARMS,
                         done.stdout)
        self.assertNotIn("Stopped by", done.stdout)


class TestItSaysSoWhenCtrlCCannotWork(unittest.TestCase):
    """The condition that made this whole investigation necessary.

    A signal ignored on entry to a shell may not be trapped or reset, so when a
    batch starts that way Ctrl-C reaches only the arm and the script's own trap
    never fires. Nothing said so, and from the terminal it looked as though the
    interrupt had been ignored.
    """

    def _run_with(self, ignore_sigint: bool) -> str:
        def preexec():
            signal.signal(signal.SIGINT, signal.SIG_IGN)

        done = subprocess.run(
            ["bash", str(SCRIPT), *ARGS], cwd=str(conftest.PROJECT_ROOT),
            env=dict(os.environ, DRY_RUN="1"), capture_output=True, text=True,
            timeout=120, preexec_fn=preexec if ignore_sigint else None)
        return done.stdout + done.stderr

    def test_it_warns_when_sigint_was_ignored_before_it_started(self):
        out = self._run_with(ignore_sigint=True)
        self.assertIn("Ctrl-C", out)
        self.assertIn("cannot stop it", out)
        self.assertIn("kill ", out, "the warning has to say how to stop it")

    def test_it_stays_quiet_when_ctrl_c_will_work(self):
        """Otherwise the warning is noise on every ordinary run, and a warning
        that always fires is one nobody reads."""
        out = self._run_with(ignore_sigint=False)
        self.assertNotIn("cannot stop it", out)


class TestAnInterruptedArmStopsTheBatch(unittest.TestCase):
    """The case no trap can catch, and the one that actually bit.

    When SIGINT is ignored on entry to the script, Ctrl-C never reaches the
    script at all - only the arm's own process sees it. The arm obeys, and the
    exit code is then the sole evidence that a human asked for this to end.
    """

    def _fake_arm(self, exit_code: int) -> tuple:
        """Run the real script with a stub standing in for run_eval.py.

        A stub, because provoking a genuine KeyboardInterrupt inside a paid arm
        is not something a test may do. What is under test here is the SCRIPT's
        reading of an exit code; that the runner produces 130 on an interrupt is
        asserted separately, against the runner.
        """
        bin_dir = SCRIPT.parent / "_stub_bin"
        os.makedirs(bin_dir, exist_ok=True)
        shim = bin_dir / "python3"
        # Three cases, and the middle one is why the first exists: the script
        # also calls run_eval.py once at the end for --summarise-arms, and
        # letting the stub answer THAT too meant `set -e` propagated the arm's
        # code from the wrong call - the test read the summarise step's exit as
        # the arm guard's verdict. Its own stamp lookups must reach real Python.
        shim.write_text(
            "#!/bin/sh\n"
            'case "$*" in\n'
            '  *--summarise-arms*) exit 0 ;;\n'
            f'  *subversionbench.run_eval*) exit {exit_code} ;;\n'
            f'  *) exec {sys.executable} "$@" ;;\n'
            'esac\n', encoding="utf-8")
        os.chmod(shim, 0o755)
        try:
            env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
            done = subprocess.run(["bash", str(SCRIPT), *ARGS],
                                  cwd=str(conftest.PROJECT_ROOT), env=env,
                                  capture_output=True, text=True, timeout=120)
            return done.returncode, done.stdout + done.stderr
        finally:
            shutil.rmtree(bin_dir, ignore_errors=True)

    def test_exit_130_from_an_arm_stops_the_whole_batch(self):
        rc, out = self._fake_arm(130)
        self.assertEqual(rc, 130, out)
        self.assertIn("interrupt in the arm in progress", out)
        self.assertEqual(out.count("[1/"), 1, out)
        self.assertNotIn("[2/", out)
        self.assertNotIn("continuing to the next one", out)

    def test_an_ordinary_failing_arm_still_does_not_stop_the_batch(self):
        """The guard this must not have broken: one bad arm may not end the
        eleven after it."""
        rc, out = self._fake_arm(1)
        self.assertIn("continuing to the next one", out)
        self.assertIn(f"[{ARMS}/", out)
        self.assertNotIn("Stopped by", out)
        self.assertEqual(rc, 0, out)

    def test_a_successful_arm_is_not_mistaken_for_either(self):
        rc, out = self._fake_arm(0)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("continuing to the next one", out)
        self.assertNotIn("Stopped by", out)


class TestTheRunnerReportsAnInterruptDistinctly(unittest.TestCase):
    """The other half: 130 has to actually come out of the runner.

    Asserted on the runner's own returns rather than by interrupting a batch,
    which would need a paid episode in flight.
    """

    def test_run_batch_returns_the_interrupt_code_and_nothing_else_new(self):
        import ast
        import pathlib

        from subversionbench.runner import EXIT_INTERRUPTED
        self.assertEqual(EXIT_INTERRUPTED, 130)

        tree = ast.parse(pathlib.Path(
            conftest.PROJECT_ROOT / "subversionbench" / "runner.py"
        ).read_text(encoding="utf-8"))
        run_batch = [n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "run_batch"]
        self.assertEqual(len(run_batch), 1)

        # THE SUCCESS PATH is what has to be gated, and saying so precisely
        # matters. Two weaker versions of this check both passed against a
        # planted defect: looking for the name EXIT_INTERRUPTED anywhere in a
        # return survived the return being made unreachable by `if False:`, and
        # looking for any `if interrupted:` returning it survived the final
        # return losing its guard entirely, because the separate
        # no-episodes-collected branch still had one. An arm that collected
        # episodes and was then interrupted is exactly the case that must not
        # report success.
        body = run_batch[0].body
        final = body[-1]
        self.assertIsInstance(final, ast.Return, ast.dump(final)[:200])
        guard = body[-2]
        self.assertIsInstance(
            guard, ast.If,
            "the last statement before run_batch's final return is not an "
            "interrupt check, so an interrupted batch that collected episodes "
            "reports the same code as a clean one")
        self.assertTrue(
            any(isinstance(p, ast.Name) and p.id == "interrupted"
                for p in ast.walk(guard.test)),
            f"expected `if interrupted:` guarding the final return, got "
            f"{ast.dump(guard.test)[:200]}")
        self.assertTrue(
            any(isinstance(s, ast.Return) and s.value is not None
                and any(isinstance(p, ast.Name) and p.id == "EXIT_INTERRUPTED"
                        for p in ast.walk(s.value))
                for s in ast.walk(guard)),
            "the guard before the final return does not return EXIT_INTERRUPTED")

        numbers = set()
        for node in ast.walk(run_batch[0]):
            if isinstance(node, ast.Return) and node.value is not None:
                numbers.update(p.value for p in ast.walk(node.value)
                               if isinstance(p, ast.Constant)
                               and isinstance(p.value, int))
        self.assertTrue(numbers <= {0, 1}, numbers)

    def test_every_keyboardinterrupt_handler_records_the_interrupt(self):
        """A rule, not a location. runner.py catches KeyboardInterrupt in two
        places - the concurrent scheduler and the sequential loop - and a third
        added later must set the flag too, or an interrupt on that path becomes
        an ordinary failed arm again and the batch carries on."""
        import ast
        import pathlib
        tree = ast.parse(pathlib.Path(
            conftest.PROJECT_ROOT / "subversionbench" / "runner.py"
        ).read_text(encoding="utf-8"))
        handlers = [n for n in ast.walk(tree)
                    if isinstance(n, ast.ExceptHandler)
                    and n.type is not None
                    and any(isinstance(p, ast.Name)
                            and p.id == "KeyboardInterrupt"
                            for p in ast.walk(n.type))]
        self.assertGreaterEqual(len(handlers), 2, len(handlers))
        silent = []
        for handler in handlers:
            sets_flag = False
            for node in ast.walk(handler):
                for target in getattr(node, "targets", []):
                    name = getattr(target, "attr", None) or getattr(
                        target, "id", None)
                    if name == "interrupted":
                        sets_flag = True
            if not sets_flag:
                silent.append(handler.lineno)
        self.assertFalse(
            silent,
            f"KeyboardInterrupt is caught at these lines without recording it, "
            f"so run_all_arms.sh will start the next arm: {silent}")

    def test_the_interrupt_flag_is_not_the_abort_flag(self):
        """`aborted` is also set by the consecutive-failure limit and by an auth
        failure. If the interrupt reused it, hitting --max-consecutive-failures
        on one arm would stop all twelve - the exact behaviour the arm guard
        exists to prevent."""
        import inspect

        from subversionbench.runner import _BatchProgress
        progress = _BatchProgress(max_consecutive_failures=1, batch_stamp="S")
        self.assertFalse(progress.interrupted)
        record = {"ok": False, "failure": {"error": "boom"}}
        self.assertTrue(progress.absorb(0, record), "should abort")
        self.assertTrue(progress.aborted)
        self.assertFalse(
            progress.interrupted,
            "a failure limit set the interrupt flag, so a rough arm would stop "
            "the whole batch")
        source = inspect.getsource(_BatchProgress)
        self.assertIn("self.interrupted = False", source)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
