#!/usr/bin/env bash
#
# Collect episodes under the HELD-OUT scenario rather than the shipped one.
#
# The held-out scenario is a reworded twin: same acts, same arms, same
# mechanism, different surface text. Running it answers whether a rate this
# benchmark reports survives a change that carries no semantic content.
#
#   ./run_heldout.sh --model x-ai/grok-4.5 --runs 10
#
# Arguments are passed straight through to run_all_arms.sh, so everything that
# works there works here. What this script adds is the three things that are
# easy to get wrong by hand:
#
#   1. It exports the decrypted bundle and points
#      SUBVERSIONBENCH_SCENARIO_BUNDLE at it. The variable has to be set before
#      python starts: scenario.py derives CLIENT_NAME, TASK_FILE_NAME and the
#      assembled arm at IMPORT, so a flag parsed later would arrive after all
#      of them were frozen. That is why the seam is an environment variable and
#      not a --scenario-bundle option.
#
#   2. It removes the plaintext afterwards, on any exit. The encrypted bundle
#      is the artefact that is kept; the plaintext is a working file, and a
#      held-out control is worth having only while it has never been published.
#
#   3. It refuses to start unless the bundle is pinned. Without a pins sidecar
#      the harness cannot stamp an episode with an identity that is not r9's,
#      and episodes carrying r9's identity would pool with a corpus they do not
#      match. heldout_tool.py --pin writes it.
#
# The results directory follows the rollout, as it does for the shipped
# scenario: run_eval defaults --output-dir to ./eval_results_$ROLLOUT_VERSION,
# and under this bundle that is the held-out rollout's own name. Pass
# --output-dir to override, but do not point it at a shipped-scenario corpus.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

cleanup() {
  # --export wrote the scenario in plaintext. Take it back out, whether the
  # batch finished, failed, or was interrupted.
  rm -f "$here/heldout/scenario_heldout.json"
}
trap cleanup EXIT INT TERM

bundle="$(python3 heldout_tool.py --export)"
export SUBVERSIONBENCH_SCENARIO_BUNDLE="$bundle"

# Say which scenario is running, every time. The whole risk with a second
# bundle is a batch collected under the wrong one, and the only defence that
# survives a tired operator is the run announcing itself.
python3 - <<'PY'
from subversionbench.rollout_pins import ROLLOUT_VERSION
print(f"Scenario: HELD-OUT (rollout {ROLLOUT_VERSION}); "
      f"the shipped scenario is untouched.")
PY

exec ./run_all_arms.sh "$@"
