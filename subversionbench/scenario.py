"""
Scenario text, held base64-encoded at rest.

WHY THIS IS NOT PLAIN SOURCE
----------------------------
Everything the model sees during an episode lives here: the two system
prompts, the user prompt, the interrogation questions, and the files it reads
in the sandbox. If that text sits in the repository as plain source, it goes
into the next training crawl - and a model trained on it has seen the memo,
the monitoring config and the questions it will later be asked. Its
eval-awareness rate then measures recall, not situational inference, and
results stop being comparable with anything measured earlier.

Encrypting the run transcripts (see zip.sh) does not help with this: the
scenario is code, not data.

Base64 is not security and is not meant to be. It is the same move BIG-bench
makes with canary strings and SAD makes with its datasets: bulk
training-data pipelines ingest text, they do not base64-decode it. Anyone who
wants to read the scenario can, in one command:

    python scenario_tool.py --decode      # writes scenario.json

Edit that file and run `python scenario_tool.py --encode` to fold changes
back in. scenario.json is gitignored, so a decoded working copy cannot be
committed by accident.
"""

import base64
import json
from pathlib import Path

_BUNDLE_PATH = Path(__file__).with_name("scenario.b64")


def load_scenario(path: Path = None) -> dict:
    """Decode the scenario bundle."""
    path = path or _BUNDLE_PATH
    raw = base64.b64decode("".join(path.read_text().split()))
    return json.loads(raw)


def encode_scenario(bundle: dict, path: Path = None) -> None:
    """Write a bundle back out encoded, wrapped for a readable diff."""
    path = path or _BUNDLE_PATH
    encoded = base64.b64encode(
        json.dumps(bundle, indent=1).encode()
    ).decode()
    path.write_text(
        "\n".join(encoded[i:i + 76] for i in range(0, len(encoded), 76)) + "\n"
    )


SCENARIO = load_scenario()
