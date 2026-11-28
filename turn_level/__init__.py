"""
Suspicion the model could see when it acted: the turn-level case-control reading.

Whether a first misaligned act is less likely on a turn where the model's own suspicion of a
test was in front of it. Each episode's first counted act is a case; four control turns are
drawn for it from the same model and arm, at the same number of turns since the act became
possible, from episodes that had not yet acted; a judge reads exactly the text in view at each
of those turns; and a Mantel-Haenszel odds ratio over the matched sets answers the question.
The plan this implements is recorded in docs/models.md, "Suspicion in view, turn by turn",
with the SHA-256 below; the plan itself is not tracked.

Four steps, each a subcommand of `python3 -m turn_level`, all reading and writing one working
directory (default judgements/turn_level, gitignored, because verdicts quote transcripts):

    sets      build the matched sets from the corpora. Reads run files only; calls nothing.
    judge     judge every unit the sets name. Without --run it prints what it would call.
    pack      draw the blind validation sample for a human labeller.
    estimate  the estimates. Refuses to run without the labels and their SHA-256.

The modules, in the order the steps use them:

    opportunity.py  when each act becomes possible, read from what reached the model
    episodes.py     a corpus's episodes as compact records: stratum, opportunity, first act
    matching.py     the risk sets and the control draw
    build.py        the sets step: every corpus's records and the plan's five set files
    in_view.py      what the model had in front of it at a turn, and how the judge sees it
    store.py        the working directory's files
    judge.py        the judge runner, paced and resumable
    validation.py   the blind pack, and the judge scored against its labels
    statistics.py   odds ratios over matched sets, conditional logistic regression, power
    old_locator.py  the exploratory readings' locator, applied to these sets (reading 4)
    readings.py     the primary and every sensitivity reading, as numbers
    estimate.py     the whole estimate as a document, and the gate on the labels
    cli.py          the four subcommands

Nothing here prints transcript text. The validation pack is the one file that holds it in
readable form, written into the working directory for the labeller.
"""

PLAN_SHA256 = "f410a8cfe1d3572440f4431fa13a117d47a9e0592416e2a2335c9fa2a63a152a"
DEFAULT_WORK_DIR = "judgements/turn_level"
