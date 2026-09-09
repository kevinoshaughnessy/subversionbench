"""
Splitting a sample into what a rater may see and what they may not.

The checks here are mostly about what is ABSENT from the pack, because a
judge-versus-human agreement figure measures nothing if the rater could see
the judge. They use field names this module was NOT written for, which is the
point: the engine is generic and a guard written only against the grader's
field names would not notice it quietly hard-coding them.
"""

import json
import os
import tempfile

from subversionbench import blinding

TEXT = "said"
SIDE = "positive"


def _items(n_true: int, n_false: int) -> list:
    """Items under names this module has no knowledge of."""
    out = []
    for i in range(n_true + n_false):
        yes = i < n_true
        out.append({
            "handle": f"thing_{i}_{'yes' if yes else 'no'}",
            "who": f"vendor/model-{i % 3}",
            SIDE: yes,
            # Long enough that a truncation is visible: at 41 characters a
            # planted `text[:200]` was a no-op and the guard below passed
            # against it.
            TEXT: f"item {i} said something. " + "then it kept going. " * 30,
        })
    return out


def _built(n_true=5, n_false=5, seed=1, block=blinding.BLOCK_SIZE):
    items = _items(n_true, n_false)
    order = blinding.labelling_order(items, seed, SIDE, block)
    return (order,
            blinding.pack(order, seed, TEXT, block),
            blinding.key(order, seed, TEXT, {"drawn_by": "a test"}))


class TestThePackCarriesNothingTheKeyCarries:
    def test_no_identifying_string_reaches_the_pack(self):
        """Derived from the key's own columns rather than a hand-written field
        list, so a column added to the sample later inherits this check
        instead of escaping it.

        STRINGS ONLY, and the limit is the point: a boolean verdict is
        indistinguishable by value from the pack's own `balanced: true`, so
        the field that matters most cannot be caught this way at all. Planting
        the verdict into the pack proved it - this guard passed and the
        field-set guard below is what failed."""
        _, pack, key = _built()
        structure = json.dumps({
            **pack,
            "episodes": [{k: v for k, v in e.items() if k != "text"}
                         for e in pack["episodes"]],
        })
        leaked = sorted({
            value
            for episode in key["episodes"]
            for field, value in episode.items()
            if field not in ("id", "block") and isinstance(value, str)
            and value in structure
        })
        assert not leaked, f"the pack exposes key values: {leaked}"

    def test_an_episode_shows_only_an_id_a_block_and_the_text(self):
        """Stated positively, and this is the guard that actually stops the
        verdict: an added field is caught by its NAME here, where the derived
        value check above is blind to a boolean. It also catches a field
        holding something the key does not carry, which that check cannot
        know about."""
        _, pack, _ = _built()
        assert {f for e in pack["episodes"] for f in e} == {
            "id", "block", "text"}

    def test_the_pack_has_no_other_top_level_field(self):
        """The same rule one level up. A per-episode field set says nothing
        about a verdict list parked beside `episodes`."""
        _, pack, _ = _built()
        assert set(pack) == {"seed", "block_size", "n", "blocks", "episodes"}
        assert {f for b in pack["blocks"] for f in b} == {
            "block", "balanced", "ids"}

    def test_the_text_is_taken_from_the_field_the_caller_named(self):
        _, pack, _ = _built()
        order, _, _ = _built()
        assert ([e["text"] for e in pack["episodes"]]
                == [row["item"][TEXT] for row in order])


class TestTheKeyIsDerivedRatherThanListed:
    def test_a_field_nobody_named_still_reaches_the_key(self):
        """The key is the only route from a label back to what it was about,
        so a column added to the sample must not fall out of the record. A
        hand-written copy list is how it would."""
        items = _items(5, 5)
        for item in items:
            item["added_later"] = "kept"
        order = blinding.labelling_order(items, 1, SIDE)
        key = blinding.key(order, 1, TEXT)
        assert all(e["added_later"] == "kept" for e in key["episodes"])

    def test_the_text_is_not_duplicated_into_the_key(self):
        _, _, key = _built()
        assert all(TEXT not in e for e in key["episodes"])

    def test_a_dropped_field_is_left_out(self):
        order, _, _ = _built()
        key = blinding.key(order, 1, TEXT, drop=("who",))
        assert all("who" not in e for e in key["episodes"])
        assert all("handle" in e for e in key["episodes"])

    def test_provenance_is_recorded_beside_the_mapping(self):
        """The key has to say which directory and which arguments produced the
        sample, because that is what a reader needs to believe the join."""
        _, _, key = _built()
        assert key["drawn_by"] == "a test" and key["seed"] == 1

    def test_an_item_using_a_reserved_field_is_refused(self):
        """`id` and `block` are the opaque handle. An item carrying one would
        be silently overwritten in the key, which breaks the join in the one
        direction nothing else checks."""
        items = _items(2, 2)
        items[0]["block"] = "mine"
        try:
            blinding.labelling_order(items, 1, SIDE, block=2)
        except ValueError:
            return
        raise AssertionError("an item overwrote the opaque handle")


class TestStoppingAtABlockBoundaryLeavesABalancedSample:
    def test_every_full_block_is_balanced_on_the_stratum(self):
        _, pack, key = _built(n_true=15, n_false=15)
        side = {e["id"]: e[SIDE] for e in key["episodes"]}
        for block in pack["blocks"]:
            if not block["balanced"]:
                continue
            sides = [side[i] for i in block["ids"]]
            assert sides.count(True) == sides.count(False) == len(sides) // 2

    def test_a_remainder_that_cannot_balance_is_marked_unbalanced(self):
        """The other direction: the flag is checked for being FALSE where the
        sides are unequal, so a version marking every block balanced would
        pass the check above and fail here."""
        _, pack, key = _built(n_true=5, n_false=11)
        side = {e["id"]: e[SIDE] for e in key["episodes"]}
        tail = [b for b in pack["blocks"] if not b["balanced"]]
        assert len(tail) == 1
        sides = [side[i] for i in tail[0]["ids"]]
        assert sides.count(True) != sides.count(False)

    def test_a_sample_that_divides_evenly_leaves_no_tail(self):
        _, pack, _ = _built(n_true=15, n_false=15)
        assert all(b["balanced"] for b in pack["blocks"])

    def test_an_odd_block_size_is_refused(self):
        """It cannot be balanced two ways, and flooring it silently would give
        blocks one item lopsided every time."""
        try:
            blinding.labelling_order(_items(5, 5), 1, SIDE, block=9)
        except ValueError:
            return
        raise AssertionError("an odd block size was accepted")

    def test_a_third_stratum_is_refused_rather_than_lumped_in(self):
        """Two-sided balancing given three classes would quietly fold one into
        another, and the pack would still claim to be balanced."""
        items = _items(4, 4)
        items[0][SIDE] = "maybe"
        try:
            blinding.labelling_order(items, 1, SIDE, block=2)
        except ValueError:
            return
        raise AssertionError("a third stratum was accepted")

    def test_one_side_alone_still_produces_a_pack(self):
        """Marked unbalanced, because it is - but a sample with nothing to
        balance against must not come back empty and look like a filter."""
        order, pack, _ = _built(n_true=6, n_false=0)
        assert len(order) == 6
        assert not any(b["balanced"] for b in pack["blocks"])


class TestTheOrderInsideABlockDoesNotBetrayTheStratum:
    def test_no_blocks_first_half_is_all_one_class(self):
        """The reason a block is shuffled rather than concatenated or
        alternated. Drawing five positives then five negatives is balanced at
        every boundary and still tells the rater that positions 1-5 of each
        block share a class. Fixed seed, so this is deterministic."""
        _, pack, key = _built(n_true=25, n_false=25, seed=7)
        side = {e["id"]: e[SIDE] for e in key["episodes"]}
        for block in pack["blocks"]:
            half = len(block["ids"]) // 2
            assert len({side[i] for i in block["ids"][:half]}) > 1, (
                f"block {block['block']} opens with one class")

    def test_a_different_seed_gives_a_different_order(self):
        """A shuffle that did nothing would pass the check above whenever the
        input happened to interleave."""
        one, _, _ = _built(n_true=25, n_false=25, seed=7)
        two, _, _ = _built(n_true=25, n_false=25, seed=8)
        assert ([r["item"]["handle"] for r in one]
                != [r["item"]["handle"] for r in two])

    def test_the_same_seed_gives_the_same_order(self):
        one, _, _ = _built(n_true=25, n_false=25, seed=7)
        two, _, _ = _built(n_true=25, n_false=25, seed=7)
        assert ([r["item"]["handle"] for r in one]
                == [r["item"]["handle"] for r in two])


class TestTheLabelTemplateCannotBeMistakenForALabelling:
    def test_an_unlabelled_row_is_null_and_not_false(self):
        """A template pre-filled with `false` makes an item nobody read
        indistinguishable from one read and judged negative - the
        absence-is-a-no error, arriving by a different door."""
        order, _, _ = _built()
        rows = blinding.label_rows(order)
        assert rows and all(r["label"] is None and r["code"] is None
                            for r in rows)

    def test_it_has_one_row_per_item_in_reading_order(self):
        order, pack, _ = _built()
        assert ([r["id"] for r in blinding.label_rows(order)]
                == [e["id"] for e in pack["episodes"]])


class TestWhatLandsOnDisk:
    def test_the_three_views_and_one_file_per_block_are_written(self):
        order, _, _ = _built(n_true=15, n_false=15)
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "pack")
            written = blinding.write_pack(order, 1, TEXT, dest)
            names = sorted(os.path.basename(p) for p in written)
        assert names == ["block_01.txt", "block_02.txt", "block_03.txt",
                         "key.SEALED.json", "labels.jsonl", "pack.json"]

    def test_the_written_pack_still_hides_the_key(self):
        """The check that matters is on the BYTES a rater opens, not on the
        dict a test built: the pack is only blind if what reaches the disk is.

        EVERY string field of the item, not just the obvious one. Checking only
        `handle` left the readable .txt rendering unguarded - a planted header
        that printed `who` beside the id passed this, and the block files are
        what a rater actually opens."""
        order, _, _ = _built(n_true=15, n_false=15)
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "pack")
            blinding.write_pack(order, 1, TEXT, dest)
            written = "".join(
                open(os.path.join(dest, name), encoding="utf-8").read()
                for name in sorted(os.listdir(dest))
                if name != "key.SEALED.json")
        leaked = sorted({
            f"{field}={value}"
            for row in order
            for field, value in row["item"].items()
            if field != TEXT and isinstance(value, str) and value in written
        })
        assert not leaked, f"the rater can see: {leaked}"

    def test_a_readable_block_shows_every_id_and_its_text(self):
        order, _, _ = _built()
        first = [r for r in order if r["block"] == 1]
        text = blinding.render_block(first, TEXT)
        for row in first:
            assert row["id"] in text and row["item"][TEXT] in text

    def test_the_labels_file_is_one_json_object_per_line(self):
        order, _, _ = _built()
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "pack")
            blinding.write_pack(order, 1, TEXT, dest)
            lines = open(os.path.join(dest, "labels.jsonl"),
                         encoding="utf-8").read().splitlines()
        rows = [json.loads(line) for line in lines]
        assert [r["id"] for r in rows] == [row["id"] for row in order]
