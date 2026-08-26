"""
Where things go on a chart, in numbers, before anything is drawn.

Axis tops, error-bar lengths, the calendar span every release chart shares, and
the two label layout passes. All of it is arithmetic over the report: no pyplot,
no figure, no file. That is the point of the seam - the layouts are the part of
the chart code most likely to be wrong, and this way they can be asserted on
directly by a suite that never imports the optional dependency.

The two layout passes are separate functions rather than one because the axes
differ in kind. On a positional axis every point sits at an integer x, so the
only question is vertical crowding. On a calendar axis two points can be days
apart, and a label's own WIDTH decides whether they collide - which is why the
date pass has to estimate text extent and the version pass does not.
"""

import math
from datetime import date, timedelta

from .report import _member_release_date


# Point labels on the combined chart sit BESIDE their marker, not above or
# below it, because the error bars own the vertical space at each x. Horizontal
# clearance, then one row of vertical separation per colliding family.
_LABEL_DX = 10
_LABEL_ROW = 11

# How close two families have to be, as a fraction of the axis height, before
# their labels are treated as colliding.
_LABEL_GAP = 0.06


# Where the release-date axis starts. Fixed rather than taken from the earliest
# model, so that adding an older model does not silently rescale every chart in
# the corpus and change what a reader remembers the spacing to look like.
#
# It is a FLOOR, not a hard left edge: release_span extends it leftward if a
# model predates it, because a point drawn outside the axis is worse than an
# axis that begins earlier than asked for.
#
# Was 2025-07-01, which put four empty months at the left of every chart: the
# earliest model in a family in r9 is kimi-k2-thinking on 2025-11-06, and
# kimi-k2 and kimi-k2-0905 are older but sit in no family here. Moving the floor
# spends the width on the range that carries points. It is still a floor, so an
# older model collected later reclaims the space automatically.
RELEASE_AXIS_START = date(2025, 11, 1)

# Horizontal clearance and one row of vertical separation per colliding label,
# the same mechanism the combined version chart uses. Two labels collide when
# they are close on BOTH axes - a calendar axis puts three deepseek and gemini
# releases within days of each other, at rates far enough apart to need no
# stagger at all.
_DATE_LABEL_DX = 8
_DATE_LABEL_ROW = 11

# Labels sit just ABOVE their point rather than centred on it. Centred is what
# the combined version chart does, and it cannot work here: the newest model in
# a family often sits at 0.0%, where a centred label straddles the x axis and
# half of it prints over the spine.
_DATE_LABEL_DY = 5

# How high a point has to sit, as a fraction of the axis, before its label is
# written below it instead of above. A 100% rate is a real answer in this corpus,
# and a label above one prints over the title.
_DATE_LABEL_CEILING = 0.88

# How close two points have to be on the x axis, as a fraction of the plotted
# span, before their labels are treated as sharing a column. Also how close to
# the right edge a point has to be before its label is written leftward.
_DATE_LABEL_XGAP = 0.09

# Mean glyph advance as a fraction of the font size, used to estimate how wide a
# label is before anything is drawn. Generous on purpose: over-estimating costs a
# row of stagger that was not needed, under-estimating costs a collision.
_LABEL_CHAR_PT = 0.6

# Roughly how many points of the figure width the axes get, once the margins are
# taken out. Only ever used to convert a label's width into days, so an estimate
# is enough - and the figure widths it divides are fixed below in the plotting
# calls.
#
# The combined figure was 500 while its legend sat to the RIGHT and took a
# quarter of the width out of the axes. With the legend underneath, the axes run
# nearly the full figure, a label covers proportionally fewer days, and leaving
# this at 500 would over-estimate every label and stagger rows that do not
# collide.
_PER_FAMILY_AXIS_PT = 540.0
_COMBINED_AXIS_PT = 700.0


def _point_label(member: dict, rate: float) -> str:
    """
    The rate and its interval, for the label above a point.

    The interval is written out beside the estimate rather than left to the
    error bar alone, because a whisker can be read off the axis only
    approximately and the numbers are what a reader copies into a write-up. A
    member with no interval - nothing collected - gets the rate alone rather
    than an empty pair of brackets.

    Percent signs are not repeated inside the brackets: the axis is already in
    percent and `86.6% [81.7, 90.3]` reads more cleanly than the alternative.
    """
    label = f"{rate:.1f}%"
    if member.get("ci95"):
        low, high = member["ci95"]
        label += f" [{low * 100:.1f}, {high * 100:.1f}]"
    return label


def _lower_error(member: dict) -> float:
    """Distance from the rate down to its Wilson lower bound, in points."""
    if not member.get("ci95"):
        return 0.0
    return max(0.0, (member["rate"] or 0) * 100 - member["ci95"][0] * 100)


def _upper_error(member: dict) -> float:
    """
    Distance from the rate up to its Wilson upper bound, in points.

    Asymmetric with the lower bound by construction: a Wilson interval around a
    rate near 0 or 100 is not centred on the estimate, which is the reason
    Wilson is used here rather than the normal approximation.
    """
    if not member.get("ci95"):
        return 0.0
    return max(0.0, member["ci95"][1] * 100 - (member["rate"] or 0) * 100)


def _label_layout(families: list, longest: int, top: float) -> dict:
    """
    Where each family's point label goes, as {(family, x): (dx, dy)} in points.

    WHY THIS IS A LAYOUT PASS AND NOT A PER-FAMILY CONSTANT
    -------------------------------------------------------
    Each family used to get a fixed corner, which cannot work: an offset chosen
    without looking at the other families pushes a label straight into one of
    them. grok's 4.3 sits at 0.0% and its fixed offset lifted the label 34
    points, landing it on kimi's marker at 13.3% - a collision created by the
    very mechanism meant to prevent one.

    So the labels at each x are laid out together. Families are sorted by rate
    and given a row each only where they are close enough to overlap, so a chart
    whose lines are well separated gets no stagger at all and stays readable.
    """
    layout = {}
    for x in range(longest):
        present = sorted(
            ((index, (family["members"][x]["rate"] or 0) * 100)
             for index, family in enumerate(families)
             if x < family["n_members"]),
            key=lambda pair: pair[1])
        row = 0
        for position, (index, rate) in enumerate(present):
            if position and rate - present[position - 1][1] < top * _LABEL_GAP:
                # Push the HIGHER of the two upward, away from the one below.
                row += 1
            else:
                row = 0
            # Lean left on the last column so a label cannot run off the axis.
            dx = -_LABEL_DX if x == longest - 1 else _LABEL_DX
            layout[(index, x)] = (dx, row * _LABEL_ROW)
    return layout

# Rounding ladder for the y axis: (data max at or below, step to round up to).
# A fixed 0-100 axis puts a family that never exceeds 15% into the bottom sixth
# of the chart, where three steps of a few points each look like one flat line.
# Scaled instead, the same three steps are legible.
_AXIS_STEPS = ((5, 1), (20, 5), (50, 10), (100, 10))

# Never scale below this, so an all-zero family gets an axis with height rather
# than a flat line on a zero-tall panel.
_MIN_AXIS_TOP = 5

# Room above the tallest point for its own label. Applied before rounding, so a
# max that lands exactly on a step still gets a step of clearance.
_AXIS_HEADROOM = 1.08


def axis_top(values) -> float:
    """
    Where the y axis should stop, given everything being plotted.

    Rounds up to a round number so the ticks read 0/5/10/15 rather than
    0/3.7/7.4. `values` should already include the error bars where they are
    drawn, or the whisker escapes the axis.

    WHAT SCALING COSTS
    ------------------
    Two per-family charts on different scales cannot be compared by eye: a
    family topping out at 15% and one topping out at 85% draw the same shape.
    That is the price of making a small family legible at all, and it is paid
    deliberately - the COMBINED chart shares one axis across families and is the
    one to read for comparison. The tick labels are the disclosure.
    """
    usable = [v for v in values if v is not None]
    top = max(usable) if usable else 0.0
    top *= _AXIS_HEADROOM
    for ceiling, step in _AXIS_STEPS:
        if top <= ceiling:
            return min(100.0, max(_MIN_AXIS_TOP,
                                  math.ceil(top / step) * step))
    return 100.0


def release_span(report: dict):
    """
    The (start, end) the release charts share, or None if no date is known.

    ONE span across every chart in the run, computed from every plotted family
    rather than per chart. Per-family calendars would each be scaled to their own
    family's dates, and then the whole point - that grok's four releases are
    tighter together than gemini's four - would be scaled away.

    The end is the latest release plotted, with no padding: the axis stops where
    the newest model is, and labels near that edge are written leftward instead.
    """
    dates = [d for family in report["families"] for member in family["members"]
             if (d := _member_release_date(member))]
    if not dates:
        return None
    start = min(RELEASE_AXIS_START, min(dates))
    end = max(dates)
    # A corpus whose models all predate the floor would otherwise ask matplotlib
    # for a zero-width or inverted axis.
    return (start, end if end > start else start + timedelta(days=30))


def _label_extent(text: str, fontsize: float, axis_width_pt: float,
                  width_days: int) -> float:
    """
    How wide a label is, in days of the calendar axis.

    Estimated from the character count rather than measured, because the layout
    has to run before anything is drawn and a real measurement needs a renderer.
    An estimate is enough: the question is only whether two labels are far
    enough apart, and _LABEL_CHAR_PT is deliberately generous.
    """
    widest = max((len(line) for line in text.split("\n")), default=1)
    return width_days * (widest * fontsize * _LABEL_CHAR_PT) / max(
        1.0, axis_width_pt)


def _date_label_layout(points: list, span: tuple, top: float,
                       labels: dict = None, fontsize: float = 8.0,
                       axis_width_pt: float = 520.0) -> dict:
    """
    Where each point's label goes, as {key: (dx, dy, ha, va)} in points.

    Same reasoning as _label_layout, and a different geometry. There the x values
    are integer columns, so collisions can only happen within a column; here x is
    continuous, so two labels collide when they are close on BOTH axes.

    WHY THIS COMPARES BOXES AND NOT DISTANCES
    -----------------------------------------
    It first compared the distance between the two POINTS against a fixed gap,
    which misses two things and produced a collision on the gemini-flash chart
    that this replaces. A label is much wider than its point - `0.5% [0.1, 2.7]`
    covers about 70 points, some 75 days on a 14-month axis - and a label near
    the right edge is written LEFTWARD, so two labels 63 days apart can still
    overlap when the left one reaches right and the right one reaches left.

    So each label is given an estimated box in calendar days, on the side it is
    actually written, and two labels share a row only when their boxes miss each
    other or their rates are far enough apart to be on different lines anyway.

    Three edges to keep a label off: the right one, where it is written leftward;
    the top, where it is written below its point instead of above; and the x axis
    itself, which is why the base offset is upward rather than centred.
    """
    start, end = span
    width = max(1, (end - start).days)
    ygap = top * _LABEL_GAP
    # The offset that pushes a label clear of its own marker, in days.
    nudge = _label_extent("x", 1.0, axis_width_pt, width) * _DATE_LABEL_DX
    # A row has to clear the whole label, not one line of it. The per-family
    # chart writes two lines - the version and its interval - and a row height
    # fixed at one line stacked them ON each other, which is a collision
    # produced by the mechanism meant to prevent one.
    tallest = max((text.count("\n") + 1
                   for text in (labels or {}).values()), default=1)
    row_pt = _DATE_LABEL_ROW * tallest
    placed, layout = [], {}
    ordered = sorted(points, key=lambda p: ((p[1] - start).days, p[2]))
    for key, when, rate in ordered:
        x = (when - start).days
        # Lean left for anything near the right edge, where a label written
        # rightward would run past the end of the axis.
        leans_left = x > width * (1 - _DATE_LABEL_XGAP)
        text = (labels or {}).get(key, "xxxxxx")
        extent = _label_extent(text, fontsize, axis_width_pt, width)
        box = ((x - nudge - extent, x - nudge) if leans_left
               else (x + nudge, x + nudge + extent))
        row = 0
        while any(prow == row and box[0] < pbox[1] and pbox[0] < box[1]
                  and abs(rate - pr) < ygap for pbox, pr, prow in placed):
            row += 1
        placed.append((box, rate, row))
        # A rate at the ceiling - 100% is a real answer here, not an artefact -
        # has no room above it, and a label written upward from one lands on the
        # title. Written downward it lands on empty axis.
        offset = _DATE_LABEL_DY + row * row_pt
        hangs_below = rate > top * _DATE_LABEL_CEILING
        layout[key] = (-_DATE_LABEL_DX if leans_left else _DATE_LABEL_DX,
                       -offset if hangs_below else offset,
                       "right" if leans_left else "left",
                       "top" if hangs_below else "bottom")
    return layout
