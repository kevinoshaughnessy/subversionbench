"""
Tests for the readmodes package, mirroring it module for module.

A PACKAGE rather than a bare directory, for the reason test_grading/__init__.py
gives: `test_init.py` here and the root's `test_init.py` are a collision under
pytest's prepend import mode unless one of them sits in a package, and being a
package is also what puts the repository root back on sys.path so
`from conftest import ...` resolves the way it does at the root.
"""
