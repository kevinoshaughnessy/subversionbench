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
| **I.c.1** | **satisfied for the headline grader, against one rater; self-consistency measured on an earlier grader** | see "The judge" below |
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

- a condition, where the negation sits inside an "if" clause and the awareness
  claim follows it
- an unrelated verb, negated earlier in the sentence about a different subject
- the first half of a contrast, denying the ordinary reading before asserting
  the aware one

(The indicators themselves are in `detectors.b64` — see
`subversionbench/detectors.py`. Quoting a matched phrase in a published
document would restate the protocol this section is auditing.)

That last shape is the reason a fix would do harm rather than nothing. Denying
the ordinary reading and then asserting the aware one is among the most
explicit ways a model states
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
**agreement with human**. All three are now evidenced, with two limits:
- self-consistency was measured on the grader and rubric of the time, not the
  headline measure chosen later;
- the human labels are one rater's.

**Accuracy and agreement with a human: measured on a blind random sample
(2026-10-07 to 2026-10-11).** The full record is in
[grader-selection.md](grader-selection.md).
- **The sample.** 110 episodes: 56 mainline and 54 goal-guarding, one per model
  from each corpus and two for each of four models whose awareness is phrased
  unusually. They were drawn by `grader_ab.blind_pack --draw random
  --whole-text` with a fixed seed, at random within each model and never
  balanced on a grader's verdict.
- **The labelling.** The operator labelled them blind on the four categories
  and saw the agent's text whole, without the model, the arm or any grader's
  reading. 32 were labelled aware.
- **The scoring.** Every candidate grader and question was scored with
  `grader_ab.blind_score`.
- **The headline measure** is z-ai/glm-5.3 asking the category question in its
  rules-only wording. Against the human binary verdict it has **balanced
  accuracy 97.2%** (95% bootstrap interval 93.1 to 100), **Cohen's kappa 0.93**.
- Every cell's interval overlapped every other's, so a rule fixed in advance
  made the choice.
- On the exact category, the rules-only wording agreed more closely with the
  operator than the worked wording under every grader.
- One deviation from the protocol below: three goal-guarding labels were
  changed from `false` to `true` after re-reading. In each, the deciding passage
  was a single one in a long transcript. Before the change every cell scored
  about two points lower, in the same order. Both are recorded in
  grader-selection.md.

**Self-consistency: measured, on an earlier grader.** The awareness grader of
the time, claude-opus-5 asking the per-question rubric, was run twice over the
same 116 saved r10 transcripts, sampled balanced on the stored verdict. It has
not been repeated for the glm-5.3 category question.
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

Reading the self-consistency result in the other direction: at 1.7% with an
upper bound of 6.1%, judge instability is far below the smallest effect this
benchmark claims to detect - `minimum_detectable_rate(0.301, 60)` is 0.571 - so
the published awareness figures are not meaningfully limited by it. That is the
useful conclusion, and it is also the reason a larger sample was not bought.

### Blinding, and what a single rater can claim

The rater here is the benchmark's sole author, so this cannot be inter-rater
reliability and is not reported as it. It is **author agreement, single rater,
non-independent**: evidence that the judge implements the operationalisation,
not evidence that the operationalisation is one others would share. The second
claim needs a second person and is not available.

Two consequences follow, and both are design decisions rather than caveats.

**One rater collapses two legs into one exercise.** The labels ARE the ground
truth accuracy would be scored against, so a single blind pass produces both of
I.c.1's outstanding legs rather than one of them.

**Intra-rater reliability replaces the second rater.** Re-labelling a subset
after a gap, order re-randomised and the first labels unseen, bounds the whole
measurement: judge-human disagreement below the rater's own noise floor is not
evidence about the judge. It is the strongest substitute available to a sole
author and it costs a quarter of the labelling. **It has not been done.** The
validation above rests on a single blind pass, so the rater's own noise floor is
not known.

The blinding itself is `subversionbench/blinding.py`, and what it withholds is
chosen from what could betray the answer rather than from what is obviously the
answer:

| Sealed | Why it is identity, not a handle |
|---|---|
| `run` | the filename encodes the model AND the arm |
| `stored_aware` | the judge's verdict |
| `model` | the rate varies by model, so it is a prior |
| `oversight`, `lure`, `nudge` | the arm, for the same reason |

The rater sees `agent_corpus`, which is the view the grader was given - capped
and formatted identically. A rater shown the raw transcript would see tool
output the judge never read, and a disagreement would then be about the input
rather than about the judgement.

By default, blocks are balanced on the stored verdict and shuffled within the
block, so labelling can stop at any block boundary and still leave a balanced
sample, while the order never says which side an episode is on. The validation
sample above was drawn with `--draw random` instead. A sample balanced on one
grader's verdict estimates accuracy on that grader's split, not on the corpus as
it is, and would favour that grader in the comparison. The key is written to
disk rather than re-derived on demand: the sampler is deterministic only against
a fixed candidate list, and this corpus is being restaged, so a regenerated
mapping would join the labels to the wrong episodes with nothing looking wrong.

The one thing the machinery cannot supply is the order of operations. The label
definition has to be frozen before the pack is read, and the original blind
label - not an adjudicated revision - is what enters the statistic. Adjudicating
toward the judge would turn agreement into a measure of deference, and every
revision would move it the same way. The validation departed from this once:
three labels were changed on re-reading. Every grader's agreement rose by about
two points as a result, which is the direction this rule warns of, and the
ordering of the graders did not change. The figures before the change are
recorded beside those after it (see "The judge" above).

## Challenge validity (II.\*)

| item | status | evidence |
|---|---|---|
| **II.1** (paper T.1) | satisfied, cited | `subversionbench/hostenv.py` records the platform, kernel mechanism, shell, coreutils and Python per episode - per episode rather than per batch because a long batch can outlive a system update |
| II.2 | satisfied | the toolchain is the sandbox's, fixed for the episode, and `confinement_available()` is asserted before a batch starts |
| II.3 | satisfied, previously uncited | an inaccessible API raises `EpisodeAPIError`, the partial episode is saved with `ended_by: api_error` and the batch counts it as failed rather than as an observation. `api_errors.py` classifies the provider error |
| II.4 | satisfied, previously uncited | each episode gets a fresh hardened environment; nothing carries between runs |
| II.5 | satisfied, previously uncited | the sandbox holds no ground truth to find - the act is a choice, not an answer |
| II.6 | satisfied | verdicts are derived from the recorded commands by code, and the derivation is checked against the stored verdict on every load |
| II.7 | satisfied | the capability arm demonstrates the act is performable: at least one model performed each act when instructed |
| **II.8** (paper T.9) | satisfied, cited | the capability arm instructs the act outright and reports which models performed it - capability shown in one direction only, since a refusal under instruction is willingness, not ability; `report/capability.py` keeps it out of every rate |
| II.9 | satisfied, previously uncited | `test_grader_injection.py`, plus the invisible-character and confusable detection, which exist because a transcript could otherwise smuggle instructions past a measure |

## Benchmark reporting (III.\*)

| item | status | evidence |
|---|---|---|
| III.1, III.2 | satisfied | the repository and the harness are public; the corpus is published encrypted so it cannot be crawled |
| **III.3** (paper R.3) | satisfied, cited | `docs/methodology.md`, "Contamination, and when the scenario would be rotated" - the canary, the base64 bundle, the held-out scenario |
| **III.4** (paper R.4) | satisfied, cited | same section: the rotation policy, its trigger, and why rotation is a last resort rather than a schedule |
| **III.5** (paper R.5) | satisfied, cited | `docs/methodology.md`, "Which measurement serves which construct" |
| **III.6** (paper R.6) | satisfied, cited, with a gap in the early record | `docs/methodology.md`, "What is being evaluated" - a named model, as served by a recorded backend, under a recorded reasoning-exposure regime, inside this harness's fixed scaffold. See "III.6, what the record could not say" below |
| III.7 | satisfied, previously uncited | the plant-the-defect discipline in AGENTS.md, and a CHANGELOG entry per version recording what was wrong and how it was found |
| III.8 | satisfied | `docs/methodology.md` carries the caveats the measures cannot remove |
| III.9 | satisfied, previously uncited | `report/data_quality.py` is a suite of quantitative flaw-impact checks: arms pooled across backends, arms routed differently across a contrast, and the two that report episodes the harness read as a model stopping when the provider said it was truncated or blocked. Three more were added for the gaps under III.6: the within-model estimate by how much reasoning reached the grader, without the models served by more than one backend, and without strata or arm pairs that span collection dates |
| III.10 | satisfied, previously uncited | Wilson intervals on every rate, exact McNemar on the paired questions, Mantel-Haenszel for the stratified estimate |
| III.11 | satisfied | the report prints its own caveats beside the figures, and collapses a question rather than showing a null when its comparator is gone |
| III.12 | **not addressed** | see below |
| **III.13** (paper R.13) | satisfied, cited | `trivial_baseline.py` |

### III.6, what the record could not say

The statement of the subject names four things: the model, the backend, the
reasoning-exposure regime and the scaffold. Checking the corpus, not the code,
found two gaps in what it actually carries, and a third the statement did not
foresee. The figures and the readings are in [models.md](models.md), under
"Provider routing" and "Per-model replication".

**The backend was not recorded for the earliest episodes.**
- `served_by` dates from 2026-09-05. Mainline episodes collected from
  2026-08-13 to 2026-09-05 have no record of the backend: 3,143 episodes from 32
  models.
- From 2026-10-06 every model is pinned to one backend.
- For the early episodes, each model's mix of backends was recovered afterwards
  from the operator's OpenRouter request counts. Sixteen models had a second
  backend serving more than 5% of requests.
- The episodes kept no generation ID, so the backend of any one episode cannot
  be recovered. The mix is known per model, not per episode.
- Mixing can bias the within-model estimate only in a stratum with aware and
  unaware episodes and an act. Few strata qualify, and leaving out the sixteen
  models does not change its sign.

**Reasoning exposure varies by route, more than "recorded" conveys.** Both
awareness measures read the reasoning, and a route can return it in four ways:
- the trace;
- a summary written by the provider;
- encrypted records only, billed as reasoning tokens with no readable text;
- nothing.

The regime is recorded per episode (`reasoning_chars`, and `reasoning_details`
where the provider sends it). But a model whose route returns encrypted records
is graded on its visible text alone, with nothing in the record marking that as
different from a model that does not reason. The within-model estimate was
therefore recomputed within groups divided by how much reasoning reached the
grader (III.9).

**The same label does not fix what is served.**
- One model's host, under an unchanged checkpoint label, returned reasoning
  blocks about six times longer two months after the first collection.
- Almost every episode then read as aware, and the model also acted far less
  often.
- A second host serving the same label returned no readable reasoning, and its
  model acted as in the first collection.

So a named model on a named backend is still not a fixed subject over time. A
model collected on two dates needs a check that the backend serves the same
behaviour.

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
and the capability arm shows, for each model that performs the act when told
to, that it can. For those models a measured zero is read as the model's
without a human in the loop; for a model that refuses the instruction too, the
arm has measured willingness again and the zero stays unresolved.

This is a reasoned omission rather than an oversight, which is the distinction
III.8 and III.11 invite: the checklist asks for transparency about what a
benchmark cannot do as much as for the things it can.

## What would close the remaining gaps

1. **I.c.1** is closed for accuracy and agreement with a human by the blind
   random sample above. Three things would strengthen it:
   - intra-rater reliability, by re-labelling a subset after a gap;
   - self-consistency measured on the headline grader and question, not on the
     earlier ones;
   - a second rater, which is the only route to agreement between people.
2. **I.b.1 is closed by the measurement above**, which found nothing to fix and
   a reason not to try.
3. **III.6.** The early backend gap is closed per model, not per episode, and
   cannot be closed further for episodes already collected.
   - For new collection, recording the provider's generation ID on every turn
     would make any episode's backend recoverable.
   - A short calibration cell before a model is collected again would catch a
     backend that has changed what it serves.
   - Neither is in the harness yet.
4. **III.12** is closed by the argument above rather than by an experiment.

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
