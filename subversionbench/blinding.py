"""
Splitting a sample into what a human rater may see and what they may not.

Any measurement of how well an automated judge agrees with a person is worth
nothing if the person can see the judge's answer, and the leak is rarely the
verdict field itself: it is the run filename that encodes the arm, the model
name beside the text, the ordering that groups one class together. So the split
is done once, here, rather than improvised per experiment.

Field-name agnostic on purpose. The caller says which field holds the text a
rater reads and which field holds the stratum to balance on, so this works on
any list of dicts - a grader sample, a keyword-screen sample, a future measure
that does not exist yet - instead of only on the one it was written for.

THE PACK IS WHAT A RATER OPENS. It holds an opaque id and the text. THE KEY IS
EVERYTHING ELSE, derived rather than listed, so a column added to the sample
later is sealed by default instead of being silently dropped from the record.
"""

import collections
import json
import os
import random

BLOCK_SIZE = 10

_RESERVED = ("id", "block")


def labelling_order(items: list, seed: int, stratum_key: str,
                    block: int = BLOCK_SIZE) -> list:
    """`[{"id", "block", "balanced", "item"}, ...]` in reading order.

    Blocks are balanced on `stratum_key` and shuffled WITHIN the block, so
    every block-boundary prefix is a balanced sample and a rater who runs out
    of time at one has not drawn a lopsided set. Shuffled within rather than
    alternated: strict alternation is also balanced at every even prefix, but
    its parity tells a rater that positions 1, 3, 5 share a class, which is a
    weaker form of exactly the leak this module exists to prevent.

    A remainder too small to fill a balanced block becomes a final block marked
    `balanced: False`. The two sides of a balanced sample are only equal in
    size by luck, and a tail quietly labelled balanced is a lopsided sample
    reported as a fair one.
    """
    if block % 2:
        raise ValueError(f"block must be even to balance two sides: {block}")
    sides = collections.defaultdict(list)
    for item in items:
        for reserved in _RESERVED:
            if reserved in item:
                raise ValueError(
                    f"an item carries the reserved field {reserved!r}, which "
                    f"the pack and key use for the opaque handle")
        sides[item[stratum_key]].append(item)
    if len(sides) > 2:
        raise ValueError(
            f"{stratum_key!r} takes {len(sides)} values; balancing here is "
            f"two-sided, so a third stratum would be silently lumped in")

    half = block // 2
    rng = random.Random(seed)
    drawn_sides = [sides[k] for k in sorted(sides, key=repr)]
    while len(drawn_sides) < 2:
        drawn_sides.append([])
    for side in drawn_sides:
        rng.shuffle(side)

    blocks = []
    while all(len(side) >= half for side in drawn_sides):
        drawn = [item for side in drawn_sides for item in side[:half]]
        for side in drawn_sides:
            del side[:half]
        rng.shuffle(drawn)
        blocks.append((True, drawn))
    tail = [item for side in drawn_sides for item in side]
    if tail:
        rng.shuffle(tail)
        blocks.append((False, tail))

    order = []
    for index, (balanced, drawn) in enumerate(blocks, start=1):
        for item in drawn:
            order.append({"id": f"ep-{len(order) + 1:03d}", "block": index,
                          "balanced": balanced, "item": item})
    return order


def pack(order: list, seed: int, text_key: str,
         block: int = BLOCK_SIZE) -> dict:
    """The rater's view: ids, blocks, and the text. Nothing else, ever.

    Whatever the caller puts in `text_key` should be the SAME view the judge
    was given. A rater shown more than the judge read - tool output, say -
    disagrees about the input, and that is not what agreement measures.
    """
    return {
        "seed": seed,
        "block_size": block,
        "n": len(order),
        "blocks": [
            {"block": index, "balanced": rows[0]["balanced"],
             "ids": [row["id"] for row in rows]}
            for index, rows in sorted(_by_block(order).items())
        ],
        "episodes": [
            {"id": row["id"], "block": row["block"],
             "text": row["item"][text_key]}
            for row in order
        ],
    }


def key(order: list, seed: int, text_key: str, provenance: dict = None,
        drop: tuple = ()) -> dict:
    """The sealed half: the id, and every field the pack does not show.

    Derived from the item rather than from a list of columns to copy, because a
    column added to the sample later must not fall out of the record - the key
    is the only route from a label back to the episode it was about.

    PERSISTED, not re-derived on demand. A deterministic sampler is
    reproducible only against a fixed candidate list, and a corpus that has
    been added to or restaged since gives the same arguments a different
    sample. Re-deriving the mapping later would join the labels to the wrong
    episodes and nothing would look wrong.
    """
    hidden = {text_key, *drop}
    return {
        "seed": seed,
        **(provenance or {}),
        "episodes": [
            {"id": row["id"], "block": row["block"],
             **{k: v for k, v in row["item"].items() if k not in hidden}}
            for row in order
        ],
    }


def label_rows(order: list) -> list:
    """One blank row per item, in reading order.

    `label` and `code` are null rather than defaulted: a template that arrives
    pre-filled makes an item nobody read indistinguishable from one read and
    judged negative. The code vocabulary belongs to the frozen codebook, not
    here - freezing it before the pack is drawn is what stops the definition
    being fitted to the cases.
    """
    return [{"id": row["id"], "block": row["block"],
             "label": None, "code": None} for row in order]


def render_block(rows: list, text_key: str) -> str:
    """One block as plain text, which is how a rater actually reads it."""
    out = []
    for row in rows:
        out.append(f"{'=' * 72}\n{row['id']}\n{'=' * 72}\n")
        out.append(row["item"][text_key])
        out.append("\n")
    return "\n".join(out)


def write_pack(order: list, seed: int, text_key: str, dest: str,
               provenance: dict = None, drop: tuple = (),
               block: int = BLOCK_SIZE) -> list:
    """Write the three views plus one readable file per block.

    The key's name says what to do with it. It is written beside the pack
    rather than elsewhere so that the labels, the pack and the mapping travel
    together - a key filed somewhere tidier is a key nobody can find when the
    labels finally need joining.
    """
    os.makedirs(dest, exist_ok=True)
    written = []
    for name, payload in (
        ("pack.json", pack(order, seed, text_key, block)),
        ("key.SEALED.json", key(order, seed, text_key, provenance, drop)),
    ):
        path = os.path.join(dest, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        written.append(path)

    labels = os.path.join(dest, "labels.jsonl")
    with open(labels, "w", encoding="utf-8") as f:
        for row in label_rows(order):
            f.write(json.dumps(row, sort_keys=True) + "\n")
    written.append(labels)

    for index, rows in sorted(_by_block(order).items()):
        path = os.path.join(dest, f"block_{index:02d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_block(rows, text_key))
        written.append(path)
    return written


def _by_block(order: list) -> dict:
    grouped = collections.defaultdict(list)
    for row in order:
        grouped[row["block"]].append(row)
    return grouped
