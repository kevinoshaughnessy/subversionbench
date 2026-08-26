"""
Tests for the reporting package, mirroring it module for module.

The `facts/` subdirectory below mirrors `reporting/facts/`. Before this it was
eight root files named `test_reporting_facts_*`, a double prefix encoding a
two-level package path into a filename - which is what a flat layout looks like
once the package it is mirroring has grown a subpackage.

A package rather than a bare directory: see test_grading/__init__.py.
"""
