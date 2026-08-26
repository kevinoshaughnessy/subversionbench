"""
Tests for the grading package, mirroring it module for module.

A PACKAGE rather than a bare directory, so a test file may share a basename
with one at the repository root. `test_grading/test_init.py` and the root's
`test_init.py` both exist, and under pytest's prepend import mode two files
of the same name are a collision unless one of them sits in a package.
It also puts the root back on sys.path for these files, which is what makes
`from conftest import ...` resolve here the way it does at the root.
"""
