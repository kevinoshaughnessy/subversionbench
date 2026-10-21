"""
An alternative scenario bundle's own rollout identity, read from its sidecar.

`rollout_pins.py` holds the SHIPPED scenario's identity and replaces it at import
when SUBVERSIONBENCH_SCENARIO_BUNDLE selects another bundle. What it replaces it
with lives in a `.pins.json` file beside that bundle, and this module is the one
place that reads it. Apart from rollout_pins because reading a sidecar is a
different job from declaring pins: that file's header calls it the data half of
the rollout check, and every reader here was growing it towards the file limit.

THE SHIPPED VALUES ARE PASSED IN, never imported. Each reader compares the
sidecar against the shipped tables - which cells must be pinned, which version
it may not claim - and rollout_pins is the module that defines them and calls
these at its own import, so importing it back would be a cycle.
"""

import json
from pathlib import Path

SIDECAR_SUFFIX = ".pins.json"


def sidecar_path():
    """The selected bundle's sidecar path, or None if the shipped bundle is."""
    # Imported here rather than at module scope: this is read very early, by
    # rollout_pins at its import. scenario.py imports nothing from the package,
    # so there is no cycle either way - this is about keeping the import graph
    # boring.
    from .scenario import bundle_is_overridden, selected_bundle_path

    if not bundle_is_overridden():
        return None
    return Path(selected_bundle_path()).with_suffix(SIDECAR_SUFFIX)


def _declared():
    """The sidecar's contents, or None if the shipped bundle is selected."""
    sidecar = sidecar_path()
    if sidecar is None:
        return None
    return json.loads(sidecar.read_text(encoding="utf-8"))


def alternative_pins(shipped_version: str, shipped_cells, shipped_acts):
    """The selected bundle's own rollout identity, or None if it is shipped.

    Returns (rollout_version, {(oversight, lure): fingerprint}, scenario_acts).
    """
    from .scenario import BUNDLE_ENV_VAR, selected_bundle_path

    sidecar = sidecar_path()
    if sidecar is None:
        return None
    if not sidecar.is_file():
        raise FileNotFoundError(
            f"{BUNDLE_ENV_VAR} selects {selected_bundle_path()}, but its rollout "
            f"pins ({sidecar.name}) are missing. Run heldout_tool.py --pin, or "
            f"scenario_tool.py --bundle <path> --pin, to compute them. They are "
            f"NOT inherited from the shipped scenario: episodes stamped with its "
            f"identity would be pooled with a scenario they do not match."
        )
    declared = json.loads(sidecar.read_text(encoding="utf-8"))
    version = str(declared.get("rollout_version", "")).strip()
    if not version or version == shipped_version:
        raise ValueError(
            f"{sidecar.name} must declare a rollout_version, and it must not "
            f"be {shipped_version!r} - that is the shipped scenario's, and "
            f"sharing it is what makes two rollouts indistinguishable."
        )
    pins = {}
    for entry in declared.get("fingerprints", []):
        pins[(bool(entry["oversight"]), bool(entry["lure"]))] = \
            str(entry["fingerprint"])
    required = _declared_cells(declared, sidecar, shipped_cells)
    # Every arm, or none. A sidecar one arm short would raise from
    # fingerprint_for() hours later, on whichever arm was missing.
    missing = required - set(pins)
    if missing:
        raise ValueError(
            f"{sidecar.name} pins {len(pins)} arm(s); {sorted(missing)} "
            f"unpinned. Every arm needs its own identity or it cannot be told "
            f"apart from another's."
        )
    extra = set(pins) - required
    if extra:
        raise ValueError(
            f"{sidecar.name} pins {sorted(extra)}, which its `cells` does not "
            f"declare. A pin for a cell the bundle says it lacks is two "
            f"statements of one fact that disagree.")
    return version, pins, alternative_acts(declared, sidecar, shipped_acts)


def _declared_cells(declared: dict, sidecar, shipped_cells) -> set:
    """The (oversight, lure) cells a bundle claims to have.

    ALL OF THE SHIPPED ONES WHEN IT DOES NOT SAY. That is what a twin is, and
    what every sidecar written before this field existed describes. A bundle in
    a world of its own may have fewer: one with no counterfactual has nothing to
    remove, and one with no lure has nothing outside the project to find. It
    lists the cells it has, and fingerprint_for refuses the others because they
    are absent from the table it reads - the same refusal as any unpinned arm.
    """
    if "cells" not in declared:
        return set(shipped_cells)
    cells = {(bool(o), bool(lure)) for o, lure in declared["cells"]}
    if not cells:
        raise ValueError(
            f"{sidecar.name} declares no cells. A bundle with no arm has "
            f"nothing to collect - omit the field to declare the shipped four.")
    unknown = cells - set(shipped_cells)
    if unknown:
        raise ValueError(
            f"{sidecar.name} declares {sorted(unknown)}, which are not "
            f"(oversight, lure) cells the harness can build.")
    return cells


def alternative_goalguard_pins(shipped_cells):
    """
    The selected bundle's goal-guarding pins, or None if it declares none.

    A SEPARATE READER RATHER THAN A FOURTH VALUE ON alternative_pins. That
    return has three and one caller unpacks exactly three; this file's own
    history with parse_batch_filename - a return that grew once and broke every
    caller - is the argument, and date_mode_from_filename and
    goalguard_from_filename are the two precedents for answering a second
    question with a second function.

    NONE IS NOT AN EMPTY TABLE. A twin that does not carry the act declares no
    pins, and goalguard_fingerprint_for goes on refusing for it - which is
    right, because there is no arm to identify. A twin that does carry the act
    must pin every cell of it: a partly-pinned table would raise hours into a
    batch, on whichever cell was missing.
    """
    declared = _declared()
    if declared is None:
        return None
    entries = declared.get("goalguard_fingerprints")
    if not entries:
        return None
    pins = {(str(e["arm"]), bool(e["oversight"]), str(e["nudge"])):
            str(e["fingerprint"]) for e in entries}
    missing = set(shipped_cells) - set(pins)
    if missing:
        raise ValueError(
            f"{sidecar_path().name} declares goal-guarding pins but leaves "
            f"{sorted(missing)} unpinned. Every cell needs its own identity or "
            f"it cannot be told apart from another's - and a table one cell "
            f"short raises on that cell alone, hours into a batch."
        )
    return pins


def alternative_variant_pins():
    """The selected bundle's variant pins, {(variant, oversight, lure): fp}.

    {} when the shipped bundle is selected or the sidecar declares none: no
    variant is then pinned, and variant_fingerprint_for refuses every one.

    THE VARIANTS THE BUNDLE DEFINES MUST ALL BE PINNED, checked against the
    bundle rather than against a table, because a variant is the bundle's own
    vocabulary and the shipped scenario has none to compare with. An unpinned
    variant would be refused hours into a batch, on the first episode of it.
    """
    declared = _declared()
    if not declared:
        return {}
    from .scenario import variant_names

    pins = {(str(e["variant"]), bool(e["oversight"]), bool(e["lure"])):
            str(e["fingerprint"])
            for e in declared.get("variant_fingerprints", [])}
    unpinned = set(variant_names()) - {v for v, _o, _l in pins}
    if unpinned:
        raise ValueError(
            f"{sidecar_path().name} leaves variant(s) {sorted(unpinned)} "
            f"unpinned. Run the bundle's --pin again: a variant collected "
            f"without its own identity pools with the control it differs from.")
    return pins


def alternative_capability_pins():
    """The selected bundle's capability pins, {(target, oversight): fp}, or None.

    None is the only answer the held-out twins give: they pin no capability
    arm, and capability_fingerprint_for goes on refusing under them rather than
    stamping the shipped scenario's capability identity on their episodes.
    """
    declared = _declared()
    if not declared or not declared.get("capability_fingerprints"):
        return None
    return {(str(e["target"]), bool(e["oversight"])): str(e["fingerprint"])
            for e in declared["capability_fingerprints"]}


def alternative_acts(declared: dict, sidecar, shipped_acts) -> tuple:
    """The act set a bundle declares, or the shipped one when it declares none.

    INHERITING IS RIGHT HERE AND WRONG FOR THE FINGERPRINTS, which is worth
    stating because this file says loudly that nothing is inherited. A
    fingerprint inherited from the shipped scenario is a claim that two
    different environments are the same one, and pools episodes that do not
    match. An act set inherited from it is a claim that the twin measures the
    same categories - which is what a twin IS, and what every sidecar written
    before this field existed describes.

    heldout_tool.py deliberately does NOT write the field. It builds twins,
    so every sidecar it produces would carry a copy of the value inherited
    here - a second spelling of one fact, which is the thing rollout_pins's
    header names as its main source of churn. A bundle measuring a different
    set of categories adds `scenario_acts` to its sidecar by hand, which is the
    same way it would gain any other claim the tool cannot infer.
    """
    if "scenario_acts" not in declared:
        return shipped_acts
    acts = tuple(str(a) for a in declared["scenario_acts"])
    if not acts:
        raise ValueError(
            f"{sidecar.name} declares an empty scenario_acts. A bundle with no "
            f"misalignment categories has no identity - omit the field to "
            f"inherit the shipped scenario's."
        )
    return acts
