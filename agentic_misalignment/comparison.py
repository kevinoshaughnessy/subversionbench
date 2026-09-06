"""The comparison as a document: every rate, every pair, every
correlation, and what the whole thing cannot say.
"""

import time
from pathlib import Path

import report
from subversionbench.config import ROLLOUT_VERSION, VERSION
from subversionbench.redaction import redact_paths

from .bundle import AWARE_POOLINGS, load_bundle
from .correlations import (best_scenario_act_pairing, correlate,
                        scenario_act_correlations)
from .pairing import build_pairs, unmatched_models, unmatched_rows
from .rates import local_act_rates, local_rates


def build_report(output_dir: str, bundle: dict = None) -> dict:
    """The whole comparison: pairs, every correlation, and what was left out."""
    bundle = bundle or load_bundle()
    # Loaded ONCE and shared by both views below. Each walked the directory for
    # itself, so every report parsed every run file twice to reach two readings
    # of the same episodes - the dominant cost of this whole script on a corpus
    # of any size.
    episodes = report.load_episodes(output_dir)
    local = local_rates(output_dir, episodes)
    document = {
        "version": VERSION,
        "rollout_version": ROLLOUT_VERSION,
        "output_dir": redact_paths(str(Path(output_dir).resolve())),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": bundle["source"],
        "is_descriptive_not_causal": True,
        "interpretation": (
            "rank correlations over five models. The suppression gap conditions "
            "on something the model did - verbalising awareness - on both "
            "sides, so it describes two populations rather than an effect"),
        "unmatched_external_models": unmatched_rows(bundle),
        "unmatched_local_models": unmatched_models(bundle, sorted(local)),
        "correlations": [],
        "pairs_by_pooling": {},
    }
    for pooling in AWARE_POOLINGS:
        pairs = build_pairs(bundle, local, pooling)
        document["pairs_by_pooling"][pooling] = pairs
        document["correlations"].append(correlate(pairs, "suppression", pooling))
        if pooling == "any_aware":
            document["correlations"].append(correlate(pairs, "level"))
    document["n_pairs"] = len(document["pairs_by_pooling"]["any_aware"])

    local_acts = local_act_rates(output_dir, episodes)
    document["scenario_act_correlations"] = scenario_act_correlations(
        bundle, local_acts)
    document["best_scenario_act_pairing"] = best_scenario_act_pairing(
        document["scenario_act_correlations"])
    return document
