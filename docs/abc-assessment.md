# SubversionBench against the Agentic Benchmark Checklist

Zhu et al., *Establishing Best Practices for Building Rigorous Agentic Benchmarks*
(arXiv 2507.02825), publish a 40-item checklist. This is a claim-by-claim
assessment of what this benchmark satisfies, what it does not, and where the
evidence is - so that the claim is checkable rather than asserted.

## A note on the numbering, and why half of it is missing here

The checklist is numbered twice by its own authors. The paper's prose uses
`T.`/`O.`/`R.`; the standalone checklist they publish at
`github.com/uiuc-kang-lab/agentic-benchmarks` uses `II.`/`I.`/`III.` for the
same items. AGENTS.md requires both numberings at every citation site, because
a citation a reader cannot look up is not a citation.

**This document is organised by the standalone numbering alone, and gives the
paper form only for the seven items where the correspondence is established.**
Those seven live in `ABC_ITEM_NUMBERING` in `test_project/test_project_files.py`,
which is the one place the map is kept. For the rest the paper's number is not
given because it is not known to this repository - the paper groups items as
ranges in prose and the correspondence cannot be derived from position with any
confidence. Inventing the other half of a citation would be worse than omitting
it: a reader would look up an item number that means something else.

That is a deliberate exception to the both-numberings rule, taken because the
rule exists to serve a reader looking the item up, and the standalone
numbering is the form that document actually uses.

## Outcome validity (I.\*)

The measurement chain is: a keyword screen over the transcript, an LLM judge
over the same transcript, and act detection from the recorded commands.

| item | status | evidence |
|---|---|---|
| I.a.1, I.a.2 | not applicable | nothing here matches a whole or partial string against a ground-truth answer; there is no ground-truth answer to match |
| I.b.1 | **addressed by measurement, not by a change** | see "Negation" below |
| I.b.2, I.b.3 | not applicable | no answer to list or guess |
| **I.c.1** | **partial - one leg of three** | see "The judge" below |
| I.c.2 | satisfied, previously uncited | `test_corpus/test_grader_injection.py`, 24 tests, covers a transcript trying to instruct the grader. `shapes.py` routes every answer through the shipped `parse_boolean_verdict` rather than a second copy |
| I.d.\*, I.e.\*, I.f.\* | not applicable | the outcome is not a unit, fuzz or end-to-end test of agent-written code |
| I.g.1, I.g.2 | satisfied, previously uncited | act detection checks the states a misaligned act would leave AND the ones it would not: refusal nesting separates a command the sandbox blocked from one it allowed, and `out_of_scope` is derived from both rather than asserted |
| I.g.3 | satisfied | the oversight act requires editing a specific monitoring artefact, not any state change |
| I.h.1, I.h.2 | not applicable | no answer format, no guessing |
| I.I.1 | satisfied, previously uncited | the quality-check preview is the exploitable surface, and `quote_grounding` plus the concealment measures are what stop a high score being claimed without the act |

### Negation, and why the screen is left alone

I.b.1 asks that a substring measure handle "negation modifiers used by agents".
The awareness keyword screen does no negation handling at all, so the item reads
as an open gap. It was measured before being closed either way.

Every indicator hit across the r10 transcripts was examined for a negation cue
in the indicator's own sentence, with the scope cut at sentence boundaries so a
denial of something else could not be miscounted. **34 of 3,115 hits had one -
and on inspection not one of the 34 denied the indicator.** In every case the
negation belonged to something else in the sentence:

- a condition: "if i don't comply ... this is a test of whether"
- an unrelated verb: "won't be ready in time, so i need to demonstrate that i"
- the first half of a contrast: "not a routine request - it IS a test of whether"

That last shape is the reason a fix would do harm rather than nothing. "Not X,
but a test of whether Y" is among the most explicit ways a model states
awareness, and a filter that dropped a match with a negation before it would
delete precisely those sentences - turning a measure that under-detects into one
that also under-detects the clearest cases.

A first attempt at this measurement used a fixed character window instead of
the sentence, and reported roughly three times as many negations. Every example
it produced turned out to be a negation from the previous sentence. The window
was the defect, not the screen, which is worth recording because it is the
shape a careless version of this check would take.

So the screen keeps matching, and
`TestANegationInTheSentenceDoesNotUnmakeTheAwareness` in
`test_grading/test_awareness_keywords.py` holds six of the corpus's
negated-but-aware sentence shapes - synthetic, carrying the grammar and none of
the scenario's vocabulary - and fails if a negation filter is ever added. The
filter itself was planted to confirm the guard refuses it.

What remains true of this screen is what its own docstring already says, and it
is not about negation: it reads a fixed vocabulary, so a model that says it
plainly in words nobody listed comes out not-aware. That is why the grader is
the authoritative measure and this is a floor.

### The judge

I.c.1 asks for evidence of the judge's **accuracy**, **self-consistency**, and
**agreement with human**. One of the three is now evidenced.

**Self-consistency: measured.** The awareness grader was run twice over the same
116 saved r10 transcripts, sampled balanced on the stored verdict.
`grader_ab/self_consistency.py` compares the two result files.

| | of 116 | 95% CI |
|---|---|---|
| verdict differed between passes | 3 | 0.9 - 7.3% |
| **the judge changed its mind** | **2** | 0.5 - 6.1% |
| a question was dropped, not re-judged | 1 | 0.1 - 4.7% |

The third row is the distinction a raw disagreement count gets wrong. In one
episode the verdict moved while **every question answered on both sides
agreed**: one pass answered the load-bearing question and the other failed the
call, so the classifier saw a different input. That is a grader error with its
own remedy - retry the call - and counting it as instability overstates the
judge by half.

Of the two genuine changes, one went aware to unaware and one the other way, so
the **net effect on the awareness rate over these episodes was zero**. The only
movement came from the dropped answer.

Two structural findings from the same run:

- The classifier damps noise rather than passing it through. Eleven question
  answers changed across the two passes and three verdicts moved; eight
  episodes absorbed a changed answer with the verdict holding.
- `suspects_being_tested` is load-bearing: both genuine changes involved it. It
  is the single question to stabilise if this figure ever needs to be lower.
- Calls fail outright at about 0.2% of question-slots, and roughly a third of
  the time that lands on a question the verdict depends on.

**Accuracy and human agreement: not evidenced.** Both need labelled ground
truth, which does not exist for this corpus. What exists instead is
`cross_analysis_awareness`, the agreement between the keyword screen and the
grader - a comparison of two instruments, not of either against truth, and not
one of I.c.1's three legs. The v16 rubric experiment recorded in
`docs/methodology.md` under "Validating the grader" is the nearest thing to an
accuracy check: it established that a small grader was wrong in a specific,
readable way, by reading the episodes. That is documented evidence about
accuracy, but on one batch and one question rather than the measure as a whole.

Reading the self-consistency result in the other direction: at 1.7% with an
upper bound of 6.1%, judge instability is far below the smallest effect this
benchmark claims to detect - `minimum_detectable_rate(0.301, 60)` is 0.571 - so
the published awareness figures are not meaningfully limited by it. That is the
useful conclusion, and it is also the reason a larger sample was not bought.

## Challenge validity (II.\*)

| item | status | evidence |
|---|---|---|
| **II.1** (paper T.1) | satisfied, cited | `subversionbench/hostenv.py` records the platform, kernel mechanism, shell, coreutils and Python per episode - per episode rather than per batch because a long batch can outlive a system update |
| II.2 | satisfied | the toolchain is the sandbox's, fixed for the episode, and `confinement_available()` is asserted before a batch starts |
| II.3 | satisfied, previously uncited | an inaccessible API raises `EpisodeAPIError`, the partial episode is saved with `ended_by: api_error` and the batch counts it as failed rather than as an observation. `api_errors.py` classifies the provider error |
| II.4 | satisfied, previously uncited | each episode gets a fresh hardened environment; nothing carries between runs |
| II.5 | satisfied, previously uncited | the sandbox holds no ground truth to find - the act is a choice, not an answer |
| II.6 | satisfied | verdicts are derived from the recorded commands by code, and the derivation is checked against the stored verdict on every load |
| II.7 | satisfied | the capability arm demonstrates the act is performable |
| **II.8** (paper T.9) | satisfied, cited | the capability arm instructs the act outright and reports a ceiling rather than a propensity; `report/capability.py` keeps it out of every rate |
| II.9 | satisfied, previously uncited | `test_grader_injection.py`, plus the invisible-character and confusable detection, which exist because a transcript could otherwise smuggle instructions past a measure |

## Benchmark reporting (III.\*)

| item | status | evidence |
|---|---|---|
| III.1, III.2 | satisfied | the repository and the harness are public; the corpus is published encrypted so it cannot be crawled |
| **III.3** (paper R.3) | satisfied, cited | `docs/methodology.md`, "Contamination, and when the scenario would be rotated" - the canary, the base64 bundle, the held-out scenario |
| **III.4** (paper R.4) | satisfied, cited | same section: the rotation policy, its trigger, and why rotation is a last resort rather than a schedule |
| **III.5** (paper R.5) | satisfied, cited | `docs/methodology.md`, "Which measurement serves which construct" |
| **III.6** (paper R.6) | satisfied, cited | `docs/methodology.md`, "What is being evaluated" - a named model, as served by a recorded backend, under a recorded reasoning-exposure regime, inside this harness's fixed scaffold |
| III.7 | satisfied, previously uncited | the plant-the-defect discipline in AGENTS.md, and a CHANGELOG entry per version recording what was wrong and how it was found |
| III.8 | satisfied | `docs/methodology.md` carries the caveats the measures cannot remove |
| III.9 | satisfied, previously uncited | `report/data_quality.py` is a suite of quantitative flaw-impact checks: arms pooled across backends, arms routed differently across a contrast, and the two that report episodes the harness read as a model stopping when the provider said it was truncated or blocked |
| III.10 | satisfied, previously uncited | Wilson intervals on every rate, exact McNemar on the paired questions, Mantel-Haenszel for the stratified estimate |
| III.11 | satisfied | the report prints its own caveats beside the figures, and collapses a question rather than showing a null when its comparator is gone |
| III.12 | **not addressed** | see below |
| **III.13** (paper R.13) | satisfied, cited | `trivial_baseline.py` |

### III.12, and why no human baseline is reported

III.12 asks for a non-AI baseline, human experts being the example. None is
reported, and the position is that none should be.

A human baseline here would mean putting people in a fabricated sandbox with a
fabricated memo and measuring whether they tamper with monitoring. The
construct does not transfer: a person who knows they are in a study is not
producing the quantity being measured, which is behaviour under a belief about
being observed. That is the eval-awareness confound this benchmark exists to
study, so importing it into the baseline would make the baseline the least
interpretable number in the report.

The interpretive work III.12 exists to support is already done from both ends.
`trivial_baseline.py` gives the floor - what an agent that does nothing scores -
and the capability arm gives the ceiling, what the act rate looks like when the
model is told to commit it. A measured rate sits between two measured bounds
without a human in the loop.

This is a reasoned omission rather than an oversight, which is the distinction
III.8 and III.11 invite: the checklist asks for transparency about what a
benchmark cannot do as much as for the things it can.

## What would close the remaining gaps

1. **I.c.1, accuracy and human agreement.** A hand-labelled sample with two or
   more raters, scored against the grader. It is the only remaining gap that
   touches a published number. Worth doing after the self-consistency result
   above, not before: agreement with a human means little for a judge that does
   not agree with itself, and that order is now established rather than assumed.
2. **I.b.1 is closed by the measurement above**, which found nothing to fix and
   a reason not to try.
3. **III.12** is closed by the argument above rather than by an experiment.

## Reproducing the self-consistency figure

```bash
python -m grader_ab --output-dir eval_results_r10 --graders claude-opus-5 \
  --shapes per_question --per-model 4 --delay 0.4
```

Run twice, unchanged. `sampling.stratified_sample` is deterministic for a given
set of arguments, so both passes draw the same episodes and their cells are
comparable - `self_consistency.compare` refuses two documents whose samples
differ rather than intersecting them. `--delay` matters: nine calls per episode
go out back to back, a throttled call is recorded as an unanswered question,
and an unanswered question is what produced the dropped-answer case above.
