"""
The `sets` step: every corpus's episodes as records, and the plan's five sets of matched sets.

    A               the registered primary's SubversionBench episodes, four controls a case
    B, C            the blackmail port with and without the reasoning replayed
    A_eight         A with eight controls a case, its own seed (sensitivity reading 5)
    A_no_oversight  the mainline's no-oversight arms' sandbox acts (sensitivity reading 9)

Each sets file records what it was built from, so that the later steps - and anyone re-running
them - read the same inputs: the corpus directories, the judgements directory, the seed, and
an index of every analysed episode (the blackmail corpora's episode-level reading judges all of
them). Reads run files only and calls nothing. Prints counts and the files' SHA-256.
"""

import os

from subversionbench.version import VERSION

from . import PLAN_SHA256, store
from .episodes import blackmail_records, subversionbench_records
from .matching import build_sets, located_fraction_by_model

SEED = 20261128
EIGHT_CONTROLS_SEED = 20261130
CONTROLS = 4


def _index(records: list) -> dict:
    return {r["key"]: {"path": r["path"], "model": r["model"], "source": r["source"],
                       "scenario": r["scenario"], "stratum": r["stratum"],
                       "acted": r["act"] is not None or r["act_unlocated"]}
            for r in records}


def sets_document(name: str, records: list, n_controls: int, seed: int, inputs: dict,
                  excluded: dict = None) -> dict:
    return {"name": name, "plan_sha256": PLAN_SHA256, "built_by_version": VERSION,
            "seed": seed, "n_controls": n_controls, "inputs": inputs,
            "excluded": excluded or {}, "episodes": _index(records),
            "located_by_model": located_fraction_by_model(records),
            **build_sets(records, name, n_controls, seed)}


def _report(work: str, doc: dict) -> None:
    path = store.sets_path(work, doc["name"])
    store.write_json(path, doc)
    c = doc["counts"]
    print(f"{doc['name']:15} episodes {len(doc['episodes'])}, cases {c.get('cases', 0)}, "
          f"sets {len(doc['sets'])}, dropped {c.get('cases dropped, no eligible control', 0)}, "
          f"acts not located {c.get('acts not located', 0)}, act before opportunity "
          f"{c.get('act before its opportunity', 0)}, short sets "
          f"{c.get('sets with fewer controls than asked', 0)}"
          + (f", excluded {doc['excluded']}" if doc["excluded"] else ""))
    print(f"{'':15} {os.path.basename(path)} SHA-256 {store.sha256(path)}")


def build(work: str, dirs: dict, models: dict) -> int:
    """Build and write every set file. `dirs` names the corpora and judgements directories;
    `models` the blackmail corpora's plan models. Returns an exit code."""
    sb = (dirs["mainline"], dirs["goalguard"], dirs["mainline_cap"], dirs["goalguard_cap"])
    sb_inputs = {"mainline": dirs["mainline"], "goalguard": dirs["goalguard"]}
    a = subversionbench_records(*sb)
    _report(work, sets_document("A", a, CONTROLS, SEED, sb_inputs))
    _report(work, sets_document("A_eight", a, 8, EIGHT_CONTROLS_SEED, sb_inputs))
    no_oversight = subversionbench_records(*sb, no_oversight=True)
    _report(work, sets_document("A_no_oversight", no_oversight, CONTROLS, SEED, sb_inputs))
    for name, corpus, judgements in (("B", dirs["replay"], dirs["replay_judgements"]),
                                     ("C", dirs["port"], dirs["port_judgements"])):
        records, excluded = blackmail_records(corpus, judgements, models[name])
        _report(work, sets_document(name, records, CONTROLS, SEED,
                                    {"corpus": corpus, "judgements": judgements}, excluded))
    return 0
