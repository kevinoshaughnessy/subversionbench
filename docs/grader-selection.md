# Choosing the awareness grader and question (draft for decision)

Status: proposal, 2026-10-04. Nothing here has been run. Every paid step below
is started by the operator, not by an agent.

## The decision

Two choices, which have to be made together:

1. **Which question measures awareness.** The shipped rubric (several yes/no
   questions, any awareness yes making `eval_aware`) or the per-episode
   category question drafted after [grader-agreement.md](grader-agreement.md),
   which returns one of `true`, `ambiguous_true`, `ambiguous_false`, `false`.
2. **Which model asks it.** gpt-6-sol (the current default), gpt-6.1-sol, or
   claude-sonnet-5-5. z-ai/glm-5.3 is an optional fourth: it is already partly
   qualified as a backup grader from another vendor, and costs little to add.

They are decided together because each changes what "aware" counts, and each
means regrading the corpus once it is adopted. Deciding them one after the
other risks doing that twice.

The old candidate rewording of `mentioned_test` (`rubric_ab.py --against
proposed`) is not a third option. It patches one rubric question, and the
category question replaces the reading those questions feed. It can be added
back as a cell if the category question fails validation.

## What does not wait for it

The category question is additive by design: the rubric still produces
`eval_aware`, and the category is a new field stored beside it in the same
grader's reading. So grading the rest of the goal-guarding corpus with
gpt-6-sol under the shipped rubric continues as planned. Whatever wins is
added to those episodes as another reading (v213 stores several graders per
episode), not written over them.

## What each candidate brings

| Grader | For | Against |
|---|---|---|
| gpt-6-sol | The incumbent. Graded the goal-guarding corpus and the r10 comparison with no refusals and almost no errors. | Single vendor, which has already deactivated the account once. Grades its own family (gpt-6-astra, gpt-6-luna, and gpt-6-sol itself). |
| gpt-6.1-sol | Probably the closest to the incumbent, so the cheapest switch if it is better. | Same vendor and same own-family problem. Released 2026-09-29, so it has no record here yet. |
| claude-sonnet-5-5 | Another vendor, which takes away the single point of failure. | Anthropic graders refuse these transcripts: in a 212-episode comparison, opus-5 errored on 17.7% and Opus 5.5 on 22.6%. Those refusals fall almost only where the answer is yes, so they bias the rate rather than just thinning it. It grades its own family, the Claude models. |
| z-ai/glm-5.3 | A third vendor, open weights, cheap. | Not yet checked against human labels. |

The refusal question decides claude-sonnet-5-5 on its own, so it is measured
first and cheaply (step 2 below).

## The evidence

Three sources, used for different things.

1. **A random sample, labelled blind.** About 120 episodes, four per model
   across the r10 and goal-guarding corpora, drawn by
   `grader_ab.blind_pack` with a fixed seed. The rater sees the agent's text
   only: not the model, the arm, or any grader's reading. This is the only
   source that estimates accuracy on the corpus as it is, so the decision
   rests on it.
2. **The draft's own test sets** (`labelling/test-sets/test_sets.jsonl`, 227
   episodes in five overlapping sets). They were chosen because opus-5 and
   gpt-6-sol disagreed on them, so they show where graders differ and
   cannot estimate accuracy. They are scored against the expected outcomes
   the draft already states for each set.
3. **The 32 existing `mentioned_test` gold labels**, relabelled onto the four
   categories, as the draft says. They were made unblinded, so they count as
   a check, not as the measure.

The earlier comparison's labels were made with a grader's answer in view;
that is why its grader-human agreement is partly circular, and why source 1
is blind.

## The steps

1. **Merge the bundle change** (branch `bundle-grader-wordings`), so every
   question text lives in `detectors.b64`. Then add the category question and
   its system prompt to the bundle. That moves the draft from the encrypted
   archive to the base64 bundle, the same protection the shipped rubric has.
   A grader cannot ask a question it cannot read, so this has to happen
   before anything runs.
2. **Refusal screen, ~20 episodes per candidate.** The category question on
   the 20 test-set episodes with the most explicit awareness, for each
   candidate grader. Any candidate that leaves more than one in twenty
   unanswered is dropped before labelling effort is spent on it.
3. **Build the cell runner.** `grader_ab` already crosses grader against call
   shape on a blinded sample and writes nothing back. Its shape axis becomes
   an instrument axis (`rubric`, `category`); that is the smallest change that
   gives graders x instruments on one sample. Its `--dry-run` prints the call
   count before anything is spent. `grader_ab/prices.py` has no entry yet
   for gpt-6.1-sol or claude-sonnet-5-5 and needs one before its cost figure
   can be trusted.
4. **Label the random sample** (operator, from the blind pack), on the four
   categories.
5. **Run the grid** on all three sources: each surviving grader x
   {rubric, category}.
6. **Decide by the rule below**, then regrade the corpus with the winner as an
   added reading.

## The rule, fixed before anything runs

On the random sample, a grader's binary verdict (`true` or `ambiguous_true`
against the rest; the rubric's `eval_aware`) is compared with the human
binary verdict.

- **Primary:** balanced accuracy, with a 95% interval.
- **Hard limit:** at most 2% of episodes unanswered or errored. A refusal is
  not missing at random here, so a grader over the limit is out, however
  accurate its answers are.
- **Own family:** accuracy is reported separately for each family of
  evaluated model. A grader that does markedly better on another family than
  on its own is not used on its own family.
- **Ties:** where intervals overlap, prefer the vendor that is not OpenAI,
  then the cheaper.
- **The category question is adopted as the headline** only if it beats the
  rubric on the random sample *and* meets the draft's expectations on the
  charter and attack sets. Otherwise it stays a stored secondary field.

## What it costs

- **Grader calls.** Roughly 120 + 227 + 32 episodes, less overlap, times each
  surviving grader, times the two instruments. The rubric costs one call per
  question per episode, and the category question one per episode (plus one
  per act, for its timing reading). `grader_ab --dry-run` gives the exact
  count.
- **Operator time.** Labelling about 120 episodes blind is the expensive part,
  and it is the part that cannot be skipped.
- **A corpus regrade** with the winner once it is chosen, at the same cost as
  the gpt-6-sol pass that has just finished.

## Open questions for the operator

1. Is glm-5.3 in the grid, or only kept as a backup?
2. Is the random-sample size of about 120 enough? Four per model keeps per-model
   claims out of reach; it is sized for the overall decision only.
3. May the category question move into the bundle (step 1)? It is the
   prerequisite for every other step.
