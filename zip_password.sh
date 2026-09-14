#!/bin/bash
#
# The one place PASSWORD is defined. Sourced by zip.sh and zip_charts.sh
# rather than each holding its own copy, so the day this changes there is one
# line to edit rather than two that can quietly drift apart.
#
# Not a secret in the credential sense - see zip.sh's own header comment: its
# job is to keep the contents out of a crawler's hands, not out of a
# determined reader's.

PASSWORD="donottrainonsubversionbench"
