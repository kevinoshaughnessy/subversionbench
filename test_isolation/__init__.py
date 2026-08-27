"""
Tests for the boundary an episode runs inside: the sandbox, what
confinement is actually available, and the environment handed to the model.

A PACKAGE rather than a bare directory: see test_grading/__init__.py,
which gives the reason - a basename may then be shared with a file in
another package, and being a package is what puts the repository root
back on sys.path so `from conftest import ...` resolves here as it does
at the root.
"""
