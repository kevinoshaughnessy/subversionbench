# Cross-model report

[← README](../README.md) · [Methodology](methodology.md) · [Scenario](scenario.md) · [Operations](operations.md) · [Report](report.md) · [Trends](trends.md)

`run_report.py` answers twelve fixed research questions across every model in a results
directory, prints them as tables, and writes the whole thing as JSON. It calls no API and
costs nothing: everything it reports is derived from summary and run files already on disk.

Where [`--compare`](operations.md#comparing-two-arms) differences two arms of one model and
`--summarise-arms` lays out every arm of one model, this is the level above both — one
question at a time, pooled across models, with the per-model breakdown underneath.

```bash
python run_report.py --output-dir eval_results_r9
```

Writes `research_report_<timestamp>.json` into `--output-dir` unless `--json-out` says
otherwise. A full pass over a corpus of a few thousand episodes takes a couple of seconds.

> **No rate, effect or p-value from a corpus is quoted below.** They go stale on every
> rollout and on every scoring correction - the v81-v83 corrections moved misalignment,
> scheming and the oversight effect - so a figure written here would be wrong shortly after it
> was written, and wrong in a document a reader consults to decide what the numbers mean. What
> each question measures, why each guard exists, and what the output looks like do not drift,
> and are what this file is for. Run the command for the answers.

---

## The twelve questions

| | question | outcome | conditioned on | stratified/split by |
|---|---|---|---|---|
| 1 | Does oversight change scheming? | scheming rate | oversight present/absent | model, nudge, lure, nudge×lure |
| 2 | Does oversight change verbalised eval awareness? | awareness rate | oversight present/absent | model, nudge, lure, nudge×lure |
| 3 | Does oversight change agentic misalignment? | misalignment rate | oversight present/absent | model, nudge, lure, nudge×lure |
| 4 | Does the nudge change verbalised eval awareness? | awareness rate | nudge `max` vs `none` (plus the 3-level trend) | model, lure |
| 5 | Does awareness go with agentic misalignment? | misalignment rate | awareness present/absent | model, nudge, lure |
| 6 | Does awareness go with oversight override? | monitoring-disabled rate | awareness present/absent | model, nudge, lure |
| 7 | Does awareness go with sandbox escape attempts? | escape-attempt rate | awareness present/absent | model, nudge, lure |
| 8 | Does awareness go with scheming? | scheming rate (episode) | awareness present/absent | model, nudge, lure |
| 9 | Does awareness go with **concealed** oversight override? | oversight-override scheming rate | awareness present/absent | model, nudge, lure |
| 10 | Does awareness go with **concealed** sandbox escape? | sandbox-escape scheming rate | awareness present/absent | model, nudge, lure |
| 11 | Does interrogation paraphrasing move concealment? | concealment rate | phrasing (paired) | act, evidence row, model |
| 12 | Does part- vs zero-evidence in Q1 move concealment? | concealment rate | phrasing (paired) | act, perturbation row, model |

Questions 1–4 and 11–12 manipulate an **experimental** factor, so they support causal
reading within the design. Questions 5–10 condition on an **observed** property of the episode — whether the
model happened to verbalise awareness — so they are associational. Awareness is not assigned;
a model that verbalises it may differ from one that does not in every other respect too. The
report says "goes with", never "causes", and neither should the write-up.

### The parallel awareness measure (questions 2 and 4)

Awareness is read from the model's reasoning **and** its visible output, so the instrument is
not constant across models. Median reasoning per episode spans more than two orders of
magnitude, and several models return none at all - most because they did not reason, and at
least one because it reasoned heavily and withheld it. A rate pooled over every model
therefore mixes a measurement with a fact about the provider route, and the pooled figure sits
below the figure for the models where reasoning came back.

So questions 2 and 4 also report the same contrast with awareness read from **visible text
alone** — a channel every model has, making the measure comparable across all 27 without
excluding any. It is built from the grader's own citations: each rubric question that answered
*true* carries a quote, and `awareness_channels` places that quote in a text-only or
reasoning-only sub-corpus using the same `agent_corpus` and `check_quote_grounding` the
grounding check already uses. No extra grader calls.

**It is a lower bound wherever reasoning came back.** It asks where the evidence the grader
*chose* to cite sits, which is not what the grader would have concluded shown visible text
only — an episode whose best evidence was in reasoning may carry weaker text evidence the
rubric would still have accepted. Answering that needs the rubric re-asked against a text-only
corpus, i.e. fresh API calls. Where no reasoning was returned the two questions coincide and
the figure is exact; those models are marked `*` in the printed table.

Both rates use one denominator — episodes where the mixed measure resolved — so only the
numerator changes. Compare against the block's `mixed_overall`, not the headline contrast
above it, which is pooled from the summaries and can differ by an episode or two.
An aware episode whose citations place in neither channel is left out of the text numerator
and counted in `n_text_undetermined`; awareness from the keyword proxy has no quotes to place
and is undetermined rather than absent, since counting it as absent would understate the
measure by a different amount per model.

The `gap` column - mixed minus text - is how much of a model's measured awareness exists only
because its provider returned reasoning. It runs from zero, for a model that verbalises
everything in visible output, to most of the model's rate. That spread is what a single
cross-model awareness rate hides.

`agreement` classifies the pair on **separation as well as sign**, because sign alone
understates the interesting case. The shape to watch for is `text_only_separates`: the mixed
measure a null while the text-only measure separates, meaning an axis moves awareness
*verbalised in visible output* while total measured awareness does not. Reported on sign alone
that reads as a contradiction; it is a finding.

Questions 5–10 use awareness as the **exposure**, not the outcome. Swapping the exposure
definition is a different analysis rather than a parallel column, so the block is deliberately
not attached there.

### The act/concealment pairing

Questions 5–7 ask whether an **act** is more likely. Questions 8–10 ask whether that act was
then **concealed** — scheming, the narrower construct and a proper subset of misalignment.
They pair up deliberately:

| act question | concealment counterpart |
|---|---|
| 5 — any misaligned act | 8 — any act, concealed |
| 6 — monitoring disabled | 9 — the override, concealed |
| 7 — sandbox escape attempted | 10 — the escape, concealed |

Question 3 pairs with question 1 the same way, on the same arms rather than conditioned on
awareness: oversight against the **wide** construct (misalignment) and against the **narrow**
one (scheming), sharing a denominator. The pair has consistently shown oversight suppressing
the *act* far more than it changes whether an act that happened gets *hidden*.

Reading each pair together is the point: an axis can move the act without moving the
concealment. That is what the awareness pair has shown - more sandbox escape attempts
alongside no within-model movement in the concealment of those attempts. Aware models probe
more and hide it no more, which is a different claim from either half alone.

Each question is answered four ways, in this order:

1. **Crude pooled** — every episode in the directory, one 2×2 table.
2. **Stratified by model** — Mantel-Haenszel, holding model constant, with a Breslow-Day
   homogeneity test, and a warning if the two estimates diverge.
3. **Per-model consistency** — direction per model, and which per-model effects survive
   multiplicity correction.
4. **By the other axes** — the same contrast within each nudge level, each lure setting, and
   for questions 1–3 each nudge×lure cell.

Questions 9–10 additionally report a **conditional rate**: of the episodes that took the act
and whose concealment was determined, how many concealed it. See
[Two denominators](#two-denominators-for-questions-9-and-10).

---

## Why both a crude and a stratified estimate

Every rate here is pooled over models whose base rates differ by more than the effects being
measured. That is the standing condition for Simpson's paradox, not a remote hazard: a crude
contrast in this corpus has pooled to a small effect one way with a single model inside it
running an order of magnitude larger the other.

The two estimands answer different questions and the report never shows one alone:

- the **crude** difference answers *what happened across this corpus*, and is partly a fact
  about which models were sampled and how many episodes each contributed;
- the **stratified** difference answers *what happens within a model, averaged over models*,
  which is the claim about the manipulation.

`mantel_haenszel()` in [`power.py`](../subversionbench/power.py) reports both a **weighted
risk difference** and a **common odds ratio**:

| | reads as | defined when |
|---|---|---|
| risk difference | percentage points, directly comparable with every crude difference in this package | always, including all-zero strata |
| odds ratio | the classical MH estimand, what an epidemiological reader looks for | only when some stratum has a discordant pair |

Rates in this eval sit near zero and most strata are all-zero, so the odds ratio is often
`None` while the risk difference stands. That is why the risk difference is printed first.

### Breslow-Day: is there one effect to pool?

A stratified average over strata that disagree is as misleading as the crude figure it
replaces, just less obviously. `breslow_day()` tests homogeneity of the odds ratio, and the
report states the verdict in words beside the estimate.

Only strata with both arms populated **and** both a success and a failure somewhere can
contribute: a stratum whose outcome never varies is consistent with every odds ratio, so it
carries no evidence about heterogeneity. Degrees of freedom follow the number of
*informative* strata, not the number of models — with rates near zero the two routinely
differ by a lot, and inflating df on sparse data is how a heterogeneity test manufactures
significance. `n_strata_used` always says which.

On r9, questions 1–4 reject homogeneity and 5–10 do not. Read the first three as averages
over genuinely different per-model effects; the oversight and nudge manipulations do not act
uniformly across models, and that heterogeneity is itself a finding rather than noise to be
pooled away.

### When the crude and stratified estimates disagree

The report does not leave the reader to notice a divergence between two numbers printed
several lines apart. `crude_vs_stratified` compares them and prints a warning when:

- **CONFOUNDED** — the crude difference is separated and the stratified one is not. It also
  says how many outcome events lie in models the stratified estimate had to drop for having
  an empty arm, because that is usually the whole explanation.
- **SIGN REVERSAL** — the two point in opposite directions. Simpson's paradox, named.

Question 9 has been the case this exists for. Its crude contrast came out separated with a
small p-value while **every outcome event sat in a single model that had no eval-aware
episodes at all**. There is no within-model comparison to make: the crude figure compares that
one model against all the others, not aware episodes against unaware ones. The stratified
estimate correctly reports no effect and an undefined test, and the warning says why.
Reporting the crude p-value as a finding would have been a straightforward false claim.
Question 10 has fired the same warning less starkly, with a separated crude difference
collapsing to an interval that crosses zero once stratified.

---

## Questions 11–12: the interrogation phrasing axes

These two are structurally unlike the rest, and the difference is not cosmetic.

The four opening-question phrasings sit on a 2×2 ([`config.py`](../subversionbench/config.py)):

| | reference | perturbation |
|---|---|---|
| **no evidence** | `zeroevidence` (default) | `zeroevidenceparaphrase` |
| **part evidence** | `partevidence` | `partevidenceparaphrase` |

Question 11 walks the **rows** (does a surface rewording move the rate?). Question 12 walks
the **columns** (does removing the observation clause move it?).

### Paired, not independent

Every phrasing is put to the **same act in the same episode**, so a phrasing contrast is
repeated measures. Fisher's exact test and the unpaired difference interval both assume
independent arms; applied here they throw away the pairing, which is most of the information —
concealment under two wordings of one question is strongly correlated.

So these questions use **exact McNemar** over the discordant pairs (the acts concealed under
one phrasing and not the other), with the concordant pairs ignored because they carry no
evidence about a difference. The exact binomial form rather than the chi-square approximation,
because the discordant counts here are single digits.

Two consequences worth stating:

- The test is **much** more powerful when responses correlate. On a synthetic case with
  identical marginals, paired p=0.008 against unpaired p=0.176.
- A paired contrast is **inherently within-model** — both measurements come from one episode —
  so the between-model confounding that Mantel-Haenszel exists to handle cannot arise. These
  two questions therefore carry no stratified block, and that absence is deliberate.

### Nothing is pooled

Neither question sums its contrasts, for two separate reasons:

1. **The same acts appear in every contrast.** Adding the two row contrasts would count every
   act twice.
2. **For question 11 the operation is not even the same on both rows.** `config.py` is
   explicit: the part-evidence pair differs by a clause **reorder**, and once the observation
   clause is removed there is nothing left to reorder past, so the zero-evidence pair differs
   by a **rewording** instead. "Does a surface change move the rate" is answerable within a
   row; "is zero evidence more perturbation-sensitive than part evidence" is **not answerable
   from these numbers at all**, and the report says so rather than inviting the comparison.

Question 12's contrast is clean in a way question 11's is not: the evidence axis is a pure
**removal** — the zero-evidence Q1 is the part-evidence Q1 with its observation clause deleted
and nothing else touched — so a difference is attributable to the evidence rather than to a
rewrite.

### The scorer-provenance confound

The default phrasing's concealment level comes from the headline `followup_response` field,
which `--reclassify` re-labels in place. Every other phrasing's level comes from the
`_by_variant` copy — and until v69 **`--reclassify` did not walk that map at all.** So any
contrast involving the default could put freshly classified verdicts on one side and older,
more keyword-scored ones on the other, and `config.py` records that this exact asymmetry
already invalidated one phrasing comparison once.

`--reclassify` now re-labels the variant map as well, from each answer's saved text, for any
answer whose verdict came from the keyword floor. That closes the repair gap that made this
confound unfixable: a spend cap during collection left 305 variant answers on one grok-4.5
corpus with keyword verdicts no read mode could replace, since `--reclassify` skipped the map
and `--reinterrogate` skips a variant already recorded. It still does **not** touch a copy of
the default phrasing inside the map — that copy is stale by construction, and re-labelling it
independently would give one phrasing two separately sampled verdicts with nothing to say
which the comparison used.

Three defences:

- The report **re-derives** each phrasing's level rather than reading the stored
  `concealment_<act>_by_variant` map, applying the same correction `settle_analysis` does: the
  default's level is taken from the headline answers, never from the map's own stale entry for
  it.
- The default arm is **synthesised from the headline field** rather than read out of the map,
  so it survives the map not holding a copy of it. `--reinterrogate` deletes that copy on
  purpose; iterating the map alone therefore lost the default side of every phrasing comparison
  on any episode that had been through it — half of questions 11 and 12, silently.
- Each contrast reports both sides' keyword-fallback rates and prints a **SCORER ASYMMETRY**
  warning when they differ by more than 5pp. It fires on contrasts that involve the default,
  whose headline answers are re-labelled while the copies are not, and stays silent where both
  sides come from copies - which is exactly the discrimination wanted.

Keyword verdicts skew towards the middle of the concealment scale, so where the warning fires,
part of the contrast may be the scorer rather than the wording.

### How to read the two axes

**Question 11 asks whether a rate survives rewording that carries no semantic content.** A
null here is the good outcome: it says the measure is reading the model rather than the
sentence. Read the paired difference and the discordant-pair counts, not the two marginal
rates - the perturbation is put to the same act in the same episode, so the pairing is the
whole design.

**Question 12 asks what the evidence clause in the opening question is worth.** It is a
manipulation rather than a robustness check: removing the clause makes the question genuinely
harder to answer, so a difference here is a finding about the instrument and not a defect in
it. Read it across both perturbation rows - an effect that appears under one wording and not
the other is weaker evidence than one replicated across both.

That is the design intent of the r7 change stated in `config.py` - "measuring whether [the
admission rate] survives the removal is the point" - and question 12 is where it is measured.
A row carrying the SCORER ASYMMETRY warning may be reporting the scorer rather than the
wording, so read the fallback rates beside it.

---

## Multiplicity

Each question runs one Fisher exact test per model. With a family that size at α=0.05, more
than one rejection is expected from noise alone, so `n_individually_significant` is not a
count of effects. The report prints that expectation next to the raw count and then applies
two corrections, because they control different things and a write-up should say which it
used:

| | controls | strictness |
|---|---|---|
| Holm–Bonferroni | family-wise error rate — the chance of **any** false rejection | stricter |
| Benjamini–Hochberg | false discovery rate — the expected **proportion** of rejections that are false | keeps more power when many hypotheses are genuinely non-null |

Both report adjusted p-values in the order given, so they attach back to the rows they came
from; the per-model table marks each row `*HB` for CI-separated / Holm / BH. A model with no
data on one side is not a hypothesis and leaves the family size — penalising every other test
for a comparison nobody made would be wrong.

This matters concretely. A question can show several individually significant models and have
**none** survive either correction - which, set against the rejections expected from noise at
that family size, is the multiplicity story rather than a set of findings. Read
`n_individually_significant` beside the expectation the report prints next to it, never on its
own.

---

## Where each number comes from

Two sources, and the split is not cosmetic.

**Questions 1–4 read `summary_*.json`.** Each arm's `n_scheming`/`n_misaligned`/`n_runs`
and its `awareness_subgroups` counts. Every figure summed is one the harness already computed at
collection time, so pooling is exact. `oversight` and `lure` are not summary fields — only
the filename carries them — so they are read back via `batch.parse_batch_filename`, the same
way every read-mode does.

**Questions 5–10 read `run_*.json`.** They condition an outcome on awareness *within* an arm,
a cross-tabulation no summary field holds. `awareness_flag()` supplies the split, preferring
the rubric grader over the keyword proxy exactly as the rest of the package does. The three
scheming verdicts come from `classify_scheming` and `classify_scheming_act`.

**The parallel awareness measure reads `transcript`.** It is the one thing here that does, and
only to place the grader's stored quotes in a channel — the transcript is dropped again
immediately, and no verdict is re-derived from it. Arms for that measure are rebuilt from
episodes rather than summaries, because no summary field carries a text-only numerator.

Otherwise nothing here loads a transcript, and nothing calls `normalise_analyses`. Every field read is
either raw (`monitoring_disabled`, `sandbox_escape_attempts`) or a sampled verdict
(`eval_awareness_grader`). The verdicts the report derives — misalignment, episode scheming,
and per-act scheming — are each cross-checked against the episode's own stored copy, and
disagreement is surfaced rather than averaged away. **A nonzero count there means run
`--resummarise` before quoting anything.** On r9 all three agree on every episode.

### Question 5 is deliberately not taken from `cross_analysis_awareness`

Every summary carries `cross_analysis_awareness`: exactly "of the episodes verbalising
awareness in this arm, how many were misaligned". Reusing the harness's own figure looks like
the principled choice and is a trap. It is `None` whenever an arm's graded episodes all fell
on one side of the split, so pooling it silently drops every uniform-awareness arm - over half
the corpus when this was measured, and not at random: precisely the arms at the extremes of
awareness. The conclusion flips on it. Pooled that way the contrast is a null; computed over
episodes it separates, because the dropped arms are the ones carrying the effect.

So question 5 is computed from episodes, and the summary-derived figure is reported beside it
as `summary_derived_cross_check` with its own arm count, so the two can be compared rather
than one quietly standing in for the other.

### Not-applicable is not zero

`monitoring_disabled` is `None`, not `False`, in every no-oversight episode: that arm has no
monitoring artefact to disable. Counting those as "did not override" is the misreading the NA
handling in
[`reporting/facts/misalignment.py`](../subversionbench/reporting/facts/misalignment.py)
exists to prevent, and it is not harmless - it puts every structurally-incapable episode in
question 6's denominator, which roughly halves both rates and the difference between them.

Question 6 therefore restricts to episodes where the act was observable, mirroring
`n_monitoring_obs_console`, and records `n_episodes_not_applicable`.
`sandbox_escape_attempts` needs no such guard — it is a list in every episode — which
`data_quality` verifies rather than assumes.

**Question 9 is restricted the same way.** `oversight_tampered` — the *act* behind
oversight-override scheming, not just the monitoring flag — is likewise `None` throughout the
no-oversight arm, so its prevalence denominator is the observable episodes rather than the
whole corpus. Question 10's act applies in every arm and is not restricted.

### Two denominators for questions 9 and 10

Mirrors the harness's own `scheming_by_act`, which reports both because they answer different
questions:

| | denominator | answers |
|---|---|---|
| **prevalence** (primary) | every episode where the act was observable | how often the model schemes this way at all — comparable with question 8 |
| **conditional** | episodes that took the act *and* whose concealment was determined | how readily this act gets hidden, independent of how often it is taken |

Both are printed. The conditional denominator is small — 130 determined oversight acts on
r9, ~650 sandbox acts — so it is flagged when it falls below `MIN_INFORMATIVE_DENOMINATOR`
(20), where the counts should be read instead of the rate.

A concealment verdict that could not be determined is a third state, not a clean episode: it
stays in the prevalence denominator, cannot reach the numerator, and is excluded from the
conditional denominator entirely. `n_scheming_undetermined` reports how many (2 on r9), since
a large count would bias every scheming rate downward.

### What the sandbox questions count — and why they differ

Question 7 counts `sandbox_escape_attempts`, the **wide** field behind the published
`sandbox_escape_rate`. Question 10 counts scheming on `out_of_scope_attempts`, the **narrow**
act key.

This is not two readings of one number. The act key also gates the interrogation, and pointed
at the wide field it asked models to account for probes they had never made — scoring honest
denials as scheming. On r1 that accounted for every one of the 7 episodes scored as scheming
on this act, which is why the act narrowed rather than just the interrogation; see the comment
on the sandbox act in [`grading/acts.py`](../subversionbench/grading/acts.py). On r9 that is roughly
770 episodes with a wide attempt against roughly 650 acts under the narrow key.

So question 7's population and question 10's are different sets by design, and the README's
caveat still applies to question 7: a single refused probe is weaker evidence than editing the
monitoring config.

---

## Data quality block

Printed before the questions, because it decides how much any of them mean.

| field | why it is there |
|---|---|
| `awareness_verdict_sources` | the keyword proxy under-detects badly - a pilot arm it scored at zero was graded well above that. A corpus resting partly on it measures something else than one that does not, so the harness refuses to pool them silently. Check this reads as grader throughout before quoting an awareness rate. |
| `n_misalignment_verdict_disagreements` | stored verdict vs re-derived. Nonzero ⇒ `--resummarise` first. |
| `n_scheming_verdict_disagreements` | the same check for the episode-level scheming verdict. |
| `n_scheming_act_verdict_disagreements` | the same check for the per-act scheming verdicts behind questions 9–10. |
| `n_scheming_undetermined` | episodes that took an act whose concealment could not be determined — in every scheming denominator, unable to reach the numerator. |
| `n_monitoring_not_applicable` | how many episodes left question 6's denominator, so the restriction is visible rather than implied. |
| `n_oversight_act_not_applicable` | the same for question 9's denominator. |
| `n_sandbox_escape_field_absent` | whether question 7's field was ever missing. |
| `duplicate_arms` | arms represented by more than one batch, which this script **pools**. |

### Duplicate arms

Pooling two batches of one arm is right when both are wanted and wrong when the second was
collected to *replace* the first. A partial batch lost to a provider outage and re-run to
full `n` leaves both on disk, and both are read — double-weighting that arm and mixing
collection conditions the run files themselves distinguish (`openrouter_provider`,
`openrouter_sort`). Neither case can be told from the other by looking, so the report lists
them and decides nothing. Move or delete the superseded batch if pooling is not what was
meant.

---

## Reading the output

Illustrative output, to show the shape and the order of the blocks. The figures in it are from
a corpus snapshot and are not current - see the note at the top of this file.

```
CRUDE POOLED: 30/1622=1.8%     vs 58/1609=3.6%     diff=-1.8%  p=0.002355  SEPARATED

STRATIFIED BY MODEL (Mantel-Haenszel - holds model constant):
    risk difference -1.7%  95% CI [-2.8%, -0.7%]  CMH chi2=10.1147 p=0.001471  (27/27 models)
    common odds ratio 0.5051  95% CI [0.3206, 0.7959]
    Breslow-Day REJECTS homogeneity: chi2=68.9227 df=14 p=3.023e-09 (15 informative model(s))

MULTIPLICITY over the 27 per-model test(s):
    uncorrected rejections: 3   expected from noise alone at alpha=0.05: 1.35
    survive Holm (family-wise): 2   survive Benjamini-Hochberg (FDR): 2
```

`SEPARATED` means the 95% interval on the **difference** excludes zero — not that the
marginal intervals fail to overlap, which is the comparison a reader is most likely to get
wrong and which systematically under-reports real differences. See
[`newcombe_diff_ci`](../subversionbench/power.py) and
[Uncertainty on every score](operations.md#uncertainty-on-every-score).

In the per-model table the trailing `*HB` flags are, in order: CI excludes zero, survives
Holm, survives Benjamini-Hochberg. `---` means none of the three.

---

## What it does not do

- **No causal claim for questions 5–10.** Awareness is observed, not assigned. Questions 11–12 *are* experimental: the phrasing is assigned.
- **No per-arm interaction test.** The nudge/lure splits are descriptive strata, not a
  fitted interaction term with its own significance test.
- **No text-only counterfactual.** The parallel measure on questions 2 and 4 places the
  grader's existing citations; it does not re-ask the rubric against a text-only corpus, so it
  is a floor rather than an estimate wherever reasoning came back. It also does not classify
  reasoning exposure per model — `reasoning_config`, `reasoning_chars`, `reasoning_details`
  and `token_usage.reasoning_tokens` are recorded per run, but this report does not read them.
- **No re-derivation.** It reads verdicts as saved. Use `--resummarise` (free) or
  `--grade-existing`/`--reclassify` (paid) to refresh them first; `data_quality` says when
  that is needed.
- **No pooling across rollout versions.** It reads whatever is in one directory, and results
  are only comparable within a rollout — see
  [Versioning](operations.md#versioning-rollouts-and-analysis).

---

For the question one level along - not "does this factor move the rate" but
"does the rate move as the version number climbs" - see
[docs/trends.md](trends.md).
