"""
Tests for collecting a batch: the arm loop, one episode, and the
orchestration around them.

A PACKAGE rather than a bare directory: see test_grading/__init__.py,
which gives the reason - a basename may then be shared with a file in
another package, and being a package is what puts the repository root
back on sys.path so `from conftest import ...` resolves here as it does
at the root.
"""
