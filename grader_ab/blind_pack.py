"""
A blinded labelling pack drawn from the grader A/B's own sample.

The blinding itself is `subversionbench.blinding`, which knows nothing about
this experiment: everything here is the two field names and the provenance
that make a grader sample the thing being blinded. Written this way so the
next measure that needs a human rater reuses the split rather than
re-improvising it, which is where a leak would come from.

What is sealed, and why each field is identity rather than a handle:

  run           encodes the model AND the arm - `..._nooversight_...`,
                `..._lure_...`. The sharpest leak in the sample.
  stored_aware  the judge's verdict, the answer the rater must not have.
  model         the rate varies by model, so it is a prior about the answer.
  nudge
  oversight
  lure          the arm, for the same reason.

`corpus` is what the rater reads, so it is the pack. `scenario` and
`stored_rubric` are dropped from the key as bulk: the rubric is the verdict
spelled out question by question, and the scenario corpus is not needed to
join a label back to an episode.

    python3 -m grader_ab.blind_pack --output-dir eval_results_r10 \
        --per-model 4 --seed 20260909 --dest eval_results_r10/labelling

The pack contains transcripts, so the destination must be a gitignored path -
`eval_results_*/` is, and is also what ./zip.sh encrypts, which keeps the pack
with the corpus it came from.
"""

from subversionbench.blinding import BLOCK_SIZE, labelling_order, write_pack

TEXT_KEY = "corpus"
STRATUM_KEY = "stored_aware"
# Bulk, not secrecy: both are recoverable from the run file the key names.
DROPPED_FROM_THE_KEY = ("scenario", "stored_rubric")


def build(candidates: list, seed: int, output_dir: str, sample_args: dict,
          dest: str, block: int = BLOCK_SIZE) -> list:
    """Blind `candidates` into `dest`. Returns the paths written."""
    order = labelling_order(candidates, seed, STRATUM_KEY, block)
    provenance = {"output_dir": output_dir, "sample_args": sample_args}
    return write_pack(order, seed, TEXT_KEY, dest, provenance=provenance,
                      drop=DROPPED_FROM_THE_KEY, block=block)


def main() -> int:
    import argparse

    from . import sampling

    parser = argparse.ArgumentParser(
        description="Build a blinded labelling pack from a stratified sample.")
    parser.add_argument("--output-dir", default="./eval_results_r10")
    parser.add_argument("--per-model", type=int, default=4)
    parser.add_argument("--oversample", nargs="*", default=[])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--block", type=int, default=BLOCK_SIZE)
    parser.add_argument("--dest", required=True)
    args = parser.parse_args()

    candidates = sampling.load_candidates(args.output_dir)
    sample = sampling.stratified_sample(
        candidates, args.per_model, oversample=set(args.oversample))
    if not sample:
        print("The sample is empty - nothing to blind.")
        return 1
    for path in build(sample, args.seed, args.output_dir,
                      {"per_model": args.per_model,
                       "oversample": sorted(args.oversample)},
                      args.dest, args.block):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
