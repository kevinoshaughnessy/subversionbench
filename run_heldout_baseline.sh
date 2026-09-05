#!/usr/bin/env bash
#
# Floor-check the detectors under the HELD-OUT scenario rather than the shipped
# one.
#
# WHY THIS EXISTS
# ---------------
# trivial_baseline.py proves the act detectors and the keyword awareness screen
# read zero for an agent that took no act. Run on its own it proves that of ONE
# scenario's text, and two of the measures it checks are functions of exactly
# that text:
#
#   - the keyword screen reads a fixed vocabulary of indicator phrases against
#     whatever the agent said. A phrase absent from the shipped documents can be
#     present in a reworded twin, and the agent that quotes the scenario back
#     would then verbalise "awareness" it never had.
#   - quote grounding exists to separate the scenario's words from the agent's.
#     The `quotes_the_scenario` fixture is built to sit exactly on that line, so
#     its cleanliness is a property of the document it quotes, not of the
#     fixture.
#
# The held-out scenario is a reworded twin - same acts, same arms, same
# artefact FILENAMES, since environment.py names those and only their contents
# come from the bundle. Different wording is precisely the axis along which a
# keyword false positive varies, which is what makes this worth running rather
# than assuming.
#
# A clean run here says the floor is a property of the detectors. A dirty one
# says the shipped floor was a property of the shipped wording, and that any
# held-out collection would carry a constant nothing was measuring.
#
# Costs nothing: no API calls unless --grade is passed through.
#
# Usage
# -----
#     ./run_heldout_baseline.sh                  # every arm, no API calls
#     ./run_heldout_baseline.sh --arm oversight  # one arm
#     ./run_heldout_baseline.sh --grade          # also the LLM grader (SPENDS)
#
# Any trivial_baseline.py flag passes straight through. Exits with its exit
# code, so this can gate a held-out collection the same way the shipped check
# gates a shipped one.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

cleanup() {
  # --export wrote the scenario in plaintext. Take it back out, whether the
  # check passed, failed, or was interrupted.
  rm -f "$here/heldout/scenario_heldout.json"
}
trap cleanup EXIT INT TERM

bundle="$(python3 heldout_tool.py --export)"
export SUBVERSIONBENCH_SCENARIO_BUNDLE="$bundle"

# Say which scenario is running, every time, and read it back through the same
# resolver the harness uses rather than echoing what was just exported - the
# risk with a second bundle is a result attributed to the wrong scenario, and
# the only defence that survives a tired operator is the run announcing itself.
python3 - <<'PY'
from subversionbench.scenario import bundle_is_overridden, selected_bundle_path
if not bundle_is_overridden():
    raise SystemExit("the override did not take - refusing to report a "
                     "held-out floor measured against the shipped scenario")
print(f"Scenario: HELD-OUT ({selected_bundle_path().name}); "
      f"the shipped scenario is untouched.")
PY

# NOT `exec`. exec replaces this shell, which discards the EXIT trap above and
# leaves the plaintext scenario on disk - measured in run_heldout.sh, and the
# same trap applies here. Called normally, `set -e` still propagates a nonzero
# exit and the trap runs as this shell finishes.
python3 trivial_baseline.py "$@"
