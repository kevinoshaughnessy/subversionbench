# Family version trends

[← README](../README.md) · [Methodology](methodology.md) · [Scenario](scenario.md) · [Operations](operations.md) · [Report](report.md) · [Trends](trends.md)

`family_trends.py` asks a different shape of question from the cross-model
report: not "does this factor move the rate" but "does the rate move as the
version number climbs". It groups every model in a results directory into
families, orders each family by version, and tests whether the rate moves
along that order. It calls no API.

Read [docs/report.md](report.md) first for the twelve questions and the
stratified machinery both scripts share - the rates here come through
`run_report.load_summaries`, so a family's figure here and a model's figure
there cannot disagree.

```bash
python3 family_trends.py --output-dir eval_results_r9
python3 family_trends.py --output-dir eval_results_r9 --metric scheming
python3 family_trends.py --output-dir eval_results_r9 --metric all
python3 family_trends.py --output-dir eval_results_r9 --version-style decimal
python3 family_trends.py --output-dir eval_results_r9 --no-charts
```

`--metric all` runs every metric in one invocation, writing a separate report and chart set for
each and sharing one timestamp across them so a single run's files sort together. It is
expanded into ordinary single-metric runs rather than a second code path, and it refuses
`--json-out`, since one path cannot hold three reports.

It reads its rates through `run_report.load_summaries`, so a family's figure here and a
model's figure there cannot disagree.

## Families are derived, never listed

A hand-written list of families is wrong the day after the next model is collected, and wrong
*silently* — a new ID simply fails to appear and the report is narrower than the corpus with
nothing to say so. So the script parses each ID into provider, stem, version, date stamp and
release-stage tags, and groups on the first two. `gemini-3.8-flash` joins `google/gemini-flash`
with no edit.

Two rules carry the weight, and both are reported in the output rather than applied silently:

**Release-stage words do not split a family.** `QUALIFIER_TAGS` holds `preview`, `thinking`,
`exp`, `latest` and similar. Without it, `gemini-3-flash-preview` is a family of one and never
gets compared with the versions that followed it — which is the comparison being asked for.
Same for `kimi-k2-thinking` against `kimi-k2.5`.

**Tier words do split one.** `flash`, `pro`, `lite`, and a size like `27b` are family identity:
`gemini-3.1-flash-lite` is not a version of `gemini-3.5-flash`, and pooling them would compare
two product lines and report the difference as a trend. Provider is in the key for the same
reason — `gpt-5.6-luna` and `openai/gpt-5.6-luna` are one model on two routes that return
different amounts of reasoning.

A date stamp is read before a version, because the version pattern matches a run of digits:
without that ordering `deepseek-v4-pro-0813` parses as version (4, 813) and sorts after a
hypothetical v4.99. Within one version, an undated member precedes a dated snapshot.

## The version-ordering judgement call

`--version-style decimal` (the default) reads `4.20` as 4.2, so it sorts **before** 4.3.
`--version-style component` reads it as major 4, minor 20 — so it sorts **after** 4.6, the way
a package manager reads a semantic version.

`decimal` is the default because it is what the vendors mean: **grok-4.20 is an older release
than grok-4.3**. That was not the original default, and the correction mattered — under
`component` the family fitted a *falling* trend (z=−3.29); read correctly it is *rising*
(z=+11.19). Reading a model ID as a semantic version was a guess about someone else's naming,
and the guess was wrong.

Every version in this corpus sorts correctly as a decimal: 3.1 < 3.5 < 3.6 < 3.7, 2.5 < 2.6,
and a future 3.8 still lands after 3.7. `component` stays available because `decimal` has its
own failure mode — a family that genuinely reaches minor 10 or beyond, where 4.10 follows 4.9
rather than preceding it. Nothing here does; if something ever does, affected families are
flagged inline and in `data_quality.families_with_ambiguous_ordering`, so it will say so.

## Two claims, reported separately

| claim | statistic | reading |
|---|---|---|
| the **trend** falls | Cochran-Armitage across ordered versions, 1 df | a fitted direction; survives one step going the other way |
| every **step** falls | consecutive differences | the monotone claim — this is what "consistently" means |

A family can satisfy the first without the second, and on r9 two of four do exactly that. The
verdict line says which.

Position is the trend score, not the release date, even though release dates are now recorded
in `model_releases.py`. The statistic is invariant to rescaling the scores but **not** to
respacing them, so equal spacing is a real assumption: it says only that the versions came in
this order. Scoring by date would be a different test with a different assumption — that the
rate moves at a constant amount per month — and no more defensible at this many models. The dates are
used for the release charts, and for nothing that carries a p-value.

Beside those, each family reports its consecutive-step contrasts and a first-versus-last
contrast — which can disagree with the steps. Under `component`, grok falls at two of three
steps yet ends *above* where it started.

## Across all families

Steps are pooled and put to an exact two-sided sign test against p=0.5. Flat steps carry no
direction and are excluded rather than split, since a family that never moves is not evidence
that rates fall. The per-family trend p-values form one hypothesis family and are corrected
with Holm and Benjamini-Hochberg, exactly as the per-model tests are above.

## Charts

With the `charts` extra installed (`pip install 'subversionbench[charts]'`) it also writes PNGs
into `charts/` under `--output-dir`, or wherever `--chart-dir` says:

- **one per family** — rate against version order, with Wilson intervals as error bars. The
  intervals are drawn rather than left to the table because the whole
  question is whether a sequence is falling, and four points with overlapping intervals is a
  different answer from four without. Bare point estimates would make every family look
  decisive. Each point is labelled with its rate and interval — `rate% [lo, hi]` — because a
  whisker can be read off the axis only approximately and the numbers are what gets copied into
  a write-up, and each tick carries its `n` with the family total in the title. The denominator
  is not constant within a family: `gemini-3.5-flash` carries 205 against its siblings' 120. The y axis is **scaled to that family's own whiskers** and rounded up to a round
  number — a family topping out at 15% draws on 0–20, not 0–100, where three steps of a few
  points each would look like one flat line.
- **one combined** — every family on one axis, colour-coded with a legend. The x axis is
  **position** in the family, not the version number: families run on their own numbering
  (`k2.5` against `3.7-flash` against `v4`), so there is no shared version axis to put them on.
  Position is what they share, and it is the axis the question is about. Point labels give the
  version. It carries the same Wilson intervals, drawn at a lighter weight than the lines so
  four families of them read as uncertainty around the shapes rather than competing with them.
  Its y axis is shared across every family, from the tallest whisker anywhere, and each legend
  entry carries that family's total.

Point labels on the combined chart are laid out in a pass over all families at once, not from a
per-family constant. An offset chosen without looking at the other families pushes a label
straight into one of them, and that is how a label at the bottom of one family's range came to
land on another family's marker. Families are sorted by rate at each position and given a row each only
where they are close enough to overlap, so a chart whose lines are well separated gets no
stagger at all.

Both charts label their whiskers as 95% Wilson intervals, and both name what `n` counts —
"episodes" for misalignment and scheming, "graded episodes" for awareness, whose denominator is
the episodes whose verdict resolved rather than every episode run.

Neither chart carries the verdict. The direction is visible, the intervals show roughly how
firm each step is, and the verdict's wording is directional — "consistently RISING, the opposite
of falling" reads as a disappointment, which is right for misalignment and wrong for awareness,
where a rise with capability is the expected result rather than a failure to improve. A caption
that means different things by metric is worse than none. The verdict stays in the console table
and the JSON, beside the counts it comes from.

**Two per-family charts on different scales cannot be compared by eye**: a family topping out
at 15% and one topping out at 85% draw the same shape. That is the price of making a small
family legible at all, and the tick labels are the disclosure. Read the combined chart for
comparison — it is the one with a common axis.

A family whose ordering depends on `--version-style` is drawn **dashed** on the combined chart
and carries a warning above the per-family one, so the line whose direction is a judgement call
is visible as such.

matplotlib is an optional extra rather than a dependency because every number plotted is
already in the table and the JSON. Without it the script prints an install hint and carries on:
an install that skips the extra loses presentation and no analysis.

## Release-date charts

Each of the two charts above is drawn a second time with the **calendar** on the x axis, from
`model_releases.py`: `release_<metric>_<family>.png` per family and `release_<metric>_all.png`
combined. Version position spaces every release equally, which is the right axis for the trend
tests and hides something the reader needs — four grok releases spanning four months and four
gemini releases spanning eight draw the same shape on it.

These charts **do not join the points up**. A segment between two releases claims a path between
them, and on a calendar axis that claim is stronger than the data supports: nothing was measured
in the months between two release dates, and the gaps are unequal, so a connecting line invites
reading a slope off empty space. Points and labels — one colour per family, the same colour that
family has on the combined version chart.

The one line each family gets is a **single straight dotted fit**: least squares of rate on
release date, weighted by episode count, drawn between that family's own first and last release
and under the markers. It is labelled on every chart that carries it, because an unlabelled
dotted line through four points reads as a trend *test*, and it is not one:

- **Weighted by n, not by inverse variance.** A rate from 239 episodes is a better estimate than
  one from 120, so an unweighted fit is wrong; but inverse-variance weighting needs `p(1-p)/n`,
  and this corpus has several rates of exactly zero, whose variance is zero and whose weight
  would therefore be infinite. One model with no misaligned episodes would drag the whole line
  onto itself. `n` is monotone in precision without that failure.
- **No p-value, no interval, and deliberately so.** The trend test is Cochran-Armitage on version
  position. Refitting the same rates on the calendar and testing *that* slope would be a second
  test of one hypothesis on one dataset, and it would assume something the position test does
  not — that the rate moves by a constant amount per month.
- **Points per month, with the span stated.** Per year extrapolates past the data: grok's four
  releases can span a few months and the same slope read per year extrapolates to a rise no
  rate can make. A month
  is the largest unit no family in this corpus outruns.
- **Never extended past the family's own releases**, which would draw a claim about models that
  do not exist.
- **A two-point family is fitted and flagged.** Two points determine a line exactly, so the fit
  repeats them and adds nothing; the chart and the JSON both say so rather than leaving the
  reader to notice.

The slope appears in the console report, in `families[].release_fit`, in the per-family chart's
caption and in each combined-chart legend entry — so, as everywhere else here, the line on the
chart is a second reading of a number the report already holds rather than the only place it
exists. A family with one dated release, or several released on the same day, gets no line and
says why.

The x axis runs from **1 November 2025 to the newest model plotted**, shared across every release
chart in a run rather than scaled per family, so the tighter spacing of one family's releases
against another's is visible rather than normalised away. The floor is a default and not a clip:
a model older than it extends the axis leftward, because a point drawn outside the axis is worse
than an axis that starts earlier than intended.

There are no error bars here — a whisker is a line — so the per-family release chart carries its
Wilson intervals in the point label's brackets, and the combined one carries none and refers the
reader to the version charts. Point labels give the version with its date stamp or release-stage
tag attached (`4-0813`, `2 (thinking)`), because two members of a family can share a version
number and two points both labelled `4` read as a mistake.

Labels are placed by the same collision pass as the combined version chart, generalised to a
continuous axis: a label moves to a new row only when another label is close on **both** axes,
is written leftward near the right edge, and hangs below its point when the point sits near the
ceiling — 100% is a real answer in this corpus, and a label above one prints over the title.

**A missing release date is an error, not a stop.** A date cannot be derived from a model ID, so
it has to be recorded by hand, and a model that has not been recorded is named loudly in the
data-quality block with the file to add it to, listed in
`data_quality.models_without_release_date`, and dropped from the release charts alone. The
charts themselves say how many members they are missing, and each combined legend entry reads
`(3 of 4 dated)`. Every table, trend, interval and p-value is unaffected, and the exit code does
not change: losing a chart is not worth losing the analysis over.

## What it does not do

- **No causal claim.** Version order is not randomised assignment, families differ in how many
  versions were collected, and nothing here knows what changed between two releases.
- **No statistic on the release dates.** They are recorded, charted, and fitted with a
  descriptive least-squares line, but every trend, interval and p-value is computed on version
  position with spacing assumed equal. The fitted slope has no p-value on purpose. A model with
  no recorded date loses its place on the release charts and nothing else.
- **No cross-family pooling of rates.** Only step *directions* are pooled, never the rates,
  which sit on incomparable baselines.
- **No metric that outruns its data.** `--metric misaligned` is derived from the act keys and
  is unaffected by grader or classifier failures; `--metric scheming` and `--metric aware`
  depend on sampled LLM verdicts, and `data_quality.metric_is_llm_dependent` says so, so a
  batch needing `--reclassify` is not read as a trend.
