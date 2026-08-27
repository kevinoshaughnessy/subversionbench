"""
Tests for the scenario text and everything that keeps it out of plaintext:
the bundle, its editing tool, invisible and confusable characters, redaction,
export, and contamination checks.

A PACKAGE rather than a bare directory: see test_grading/__init__.py,
which gives the reason - a basename may then be shared with a file in
another package, and being a package is what puts the repository root
back on sys.path so `from conftest import ...` resolves here as it does
at the root.
"""
