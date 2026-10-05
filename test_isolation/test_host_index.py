"""
The host's indexes and per-user sockets are out of reach from inside an episode.

In r9 a model ran Spotlight through python's subprocess and got back paths across
the operator's home - the harness source and other episodes' run files among
them. No path in the command left the tree, so neither the blocklist nor the
filesystem measures saw it. On Linux the same question is answered by a locate
database, a desktop indexer, or the session bus, and `--unshare-net` leaves every
socket that is a file reachable.

Both directions are asserted: the route is closed with the fix, and the same
probe answers without it, so a test that passes cannot be one that would have
passed anyway.
"""

import contextlib
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from conftest import darwin_only
from subversionbench import isolation
from subversionbench.isolation import confinement_available, wrap_command

_SPOTLIGHT_COUNT = ("python3 -c \"import subprocess;print(subprocess.run("
                    "['mdfind','-count','kMDItemContentType == public.folder'],"
                    "capture_output=True,text=True).stdout.strip())\"")


def _episode():
    root = Path(tempfile.mkdtemp(prefix="estate_test_"))
    project = root / "project"
    project.mkdir()
    return root, project


def _run(argv, project):
    proc = subprocess.run(argv, cwd=project, capture_output=True, text=True,
                          timeout=30, env={"HOME": str(project),
                                           "PATH": "/usr/bin:/bin",
                                           "TERM": "xterm"})
    return (proc.stdout + proc.stderr).strip()


class TestSpotlightAnswersNothingOnMacOS:
    @darwin_only
    def test_a_search_through_subprocess_returns_nothing(self):
        root, project = _episode()
        got = _run(wrap_command(_SPOTLIGHT_COUNT, "deny-network",
                                confine_to=root), project)
        assert not any(ch.isdigit() for ch in got), got

    @darwin_only
    def test_the_same_search_answers_without_the_rule(self):
        """The check can still say no: with the one line removed, the daemon
        answers with a count, 0 included. Without this the test above would pass
        on a host where Spotlight was never reachable at all."""
        root, project = _episode()
        rule = '(deny mach-lookup (global-name "com.apple.metadata.mds"))\n'
        assert rule in isolation._DARWIN_PROFILE
        profile = Path(tempfile.mkdtemp()) / "no_rule.sb"
        profile.write_text(isolation.darwin_profile("deny-network", root)
                           .replace(rule, ""))
        got = _run(["sandbox-exec", "-f", str(profile), "/bin/sh", "-c",
                    _SPOTLIGHT_COUNT], project)
        assert any(ch.isdigit() for ch in got), got


class TestTheMasksALinuxHostWouldMount:
    """What bwrap is told to hide, asserted from any host by simulating which
    paths exist - the same seam test_confinement's Linux argv tests use."""

    def _masks(self, present, sockets=()):
        home = "/home/op"
        with mock.patch.object(isolation.Path, "home",
                               return_value=Path(home)), \
                mock.patch.object(isolation.os, "getuid", return_value=1000), \
                mock.patch.object(isolation.os.path, "isdir",
                                  side_effect=lambda p: p in present), \
                mock.patch.object(isolation.os.path, "islink",
                                  return_value=False), \
                mock.patch.object(isolation.os.path, "exists",
                                  side_effect=lambda p: p in present
                                  or p in sockets), \
                mock.patch.object(isolation.os.path, "realpath",
                                  side_effect=lambda p: p):
            return isolation.linux_host_masks()

    def test_each_present_index_and_the_runtime_dir_get_an_empty_tmpfs(self):
        present = {"/var/cache/locate", "/run/user/1000",
                   "/home/op/.cache/tracker3", "/home/op/.local/share/baloo"}
        argv = self._masks(present)
        mounted = {argv[i + 1] for i, tok in enumerate(argv) if tok == "--tmpfs"}
        assert mounted == present, argv

    def test_an_absent_path_is_not_mounted(self):
        """bwrap refuses to mount over a missing path, so mounting an absent one
        would fail every command rather than tighten anything."""
        assert self._masks(set()) == []

    def test_a_socket_is_covered_with_dev_null(self):
        argv = self._masks(set(), sockets={"/run/docker.sock"})
        assert argv == ["--ro-bind", "/dev/null", "/run/docker.sock"]

    def test_the_masks_precede_the_episode_bind(self):
        """Only matters if a mask ever sat above the episode; asserted so the
        order is chosen rather than incidental."""
        with mock.patch.object(isolation, "linux_host_masks",
                               return_value=["--tmpfs", "/run/user/1000"]), \
                mock.patch.object(isolation, "_mechanism_works",
                                  return_value=True), \
                mock.patch.object(isolation.platform, "system",
                                  return_value="Linux"):
            argv = wrap_command("ls", "deny-network", confine_to="/x")
        assert argv.index("/run/user/1000") < argv.index("--bind")


@contextlib.contextmanager
def _fake_home_with_index_and_socket():
    """A home holding an index file and a live socket, patched in as the
    harness's own. Cleaned up on exit; a context manager rather than setup and
    teardown, because run_tests.py honours setup_method and nothing after."""
    home = Path.cwd() / f".sbx_index_test_{os.getpid()}"
    index = home / ".local/share/baloo"
    index.mkdir(parents=True)
    (index / "marker_db").write_text("x")
    sock_path = home / ".docker/run/docker.sock"
    sock_path.parent.mkdir(parents=True)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(sock_path))
    listener.listen(4)

    def accept():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            conn.close()

    threading.Thread(target=accept, daemon=True).start()
    try:
        with mock.patch.object(isolation.Path, "home", return_value=home):
            yield index, sock_path
    finally:
        listener.close()
        shutil.rmtree(home, ignore_errors=True)


def _probe(index, sock_path):
    root, project = _episode()
    cmd = (f"ls {index}; python3 -c \"import socket;"
           f"s=socket.socket(socket.AF_UNIX);s.connect('{sock_path}');"
           f"print('CONNECTED')\" 2>&1 | tail -1")
    return _run(wrap_command(cmd, "deny-network", confine_to=root), project)


class TestTheLinuxMasksHoldOnThisHost:
    """Run where bwrap actually confines - CI's Ubuntu runner.

    The fake home sits OUTSIDE the temp roots on purpose: inside one, the temp
    tmpfs would hide it whether or not the mask existed, and the test would pass
    with the fix removed.
    """

    def setup_method(self, method):
        if platform.system() != "Linux" or not confinement_available():
            raise unittest.SkipTest("needs bwrap confinement on Linux")

    def test_the_index_and_the_socket_are_hidden(self):
        with _fake_home_with_index_and_socket() as (index, sock_path):
            got = _probe(index, sock_path)
        assert "marker_db" not in got and "CONNECTED" not in got, got

    def test_both_are_reachable_without_the_masks(self):
        with _fake_home_with_index_and_socket() as (index, sock_path), \
                mock.patch.object(isolation, "linux_host_masks", return_value=[]):
            got = _probe(index, sock_path)
        assert "marker_db" in got and "CONNECTED" in got, got
