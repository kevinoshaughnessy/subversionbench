"""
Tests about the repository itself rather than about a module: packaging,
declared dependencies, CI, the conventions every source file must follow, and
the documents that describe them.

A PACKAGE rather than a bare directory: see test_grading/__init__.py,
which gives the reason - a basename may then be shared with a file in
another package, and being a package is what puts the repository root
back on sys.path so `from conftest import ...` resolves here as it does
at the root.
"""
