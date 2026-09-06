"""
Cross the grader MODEL against the grader CALL SHAPE, on saved transcripts.

Why this exists
---------------
Two cost questions were open, and neither is answerable by reasoning about it.

The grader asks nine rubric questions per episode, one API call each, sharing a
prompt-cached corpus. Measured over the r9 corpus that is 41,904 calls and about
$263, and the cache WRITE costs more than all nine reads combined - the corpus is
written once at 1.25x and re-read nine times at 0.1x. Asking all nine in one call
would drop effective input tokens 44%. Separately, the default grader moved from
claude-haiku-4-5 to claude-opus-5 in v16 because Haiku could not hold the
scenario-internal versus meta distinction (see rubric_ab.py, which recorded that
experiment); claude-sonnet-5 sits between them and was never tried.

Accuracy comes first here, so neither change ships on the strength of its price.
This script measures what each costs in agreement before anything is adopted.

WHY THE BATCHED ASKER LIVES IN THIS SCRIPT AND NOT IN grading/
--------------------------------------------------------------
A call-shape setting in the production grader would fork the corpus: episodes
graded under each shape are not poolable until proven equivalent, and if they
are equivalent there is no reason to keep two. `detect_eval_awareness_grader`
also routes every question through `ask_rubric_question` precisely so that
rubric_ab.py cannot drift from production - a second shape in there means that
experiment validates a path nobody runs.

So the batched asker is built HERE, out of the same primitives the shipped one
uses - same system prompt, same untrusted-text fencing, same strict verdict
parser - as a faithful preview. Adopting it means moving this function into
grading/grader.py, recording the shape in score_provenance, and re-grading the
whole corpus under it. That is the price of a clean instrument and it is not
avoided by leaving both shapes switchable.

WHAT IT MEASURES, and why each read-out is here
-----------------------------------------------
The reference cell is claude-opus-5 / per_question - what the corpus was graded
with. It is RE-RUN rather than read from the run files, because graders are
non-deterministic: comparing a new cell against stored labels conflates the
change with ordinary run-to-run variation. The fresh reference against the
stored labels is reported separately, and that difference IS the noise floor
every other comparison has to beat.

  per-question rates      where a cell diverges, not just whether it does.
  position gradient       THE pre-registered read-out for batching. Nine
                          answers with quotes in one generation invites the late
                          ones to degrade. Independent calls cannot produce a
                          gradient, so the shipped shape is a flat control and
                          any slope under batching was caused by batching.
  quote grounding         the other way output pressure shows up: a quote that
                          is no longer verbatim.
  signal correlation      the contamination check, and the subtlest risk.
                          Batched, question seven is answered having just
                          written question three. The five eval-signal questions
                          overlap by design and classify_awareness_from_rubric
                          counts DISTINCT SPANS across them, so answers that
                          become correlated by construction change what that
                          logic is fed even where per-question accuracy looks
                          unchanged.
  failure granularity     today one bad reply costs one answer of nine. Batched
                          it costs all nine, so grading_failed fires on the
                          episode. A robustness regression independent of
                          accuracy.
  verdict agreement       the bottom line: does the published eval_aware flag
                          move, computed through the real deterministic
                          classifier rather than a proxy.

Nothing is written back to any run file: this reads transcripts and reports.

COST IS MEASURED, NOT ESTIMATED FROM A CALL COUNT. Every call's real token
usage - including OUTPUT, which is what a model that cannot disable thinking
(claude-fable-5) spends unknown amounts of - is captured off the API response
and priced from PRICES_PER_MTOK, a snapshot table kept in this file because no
pricing table exists anywhere else in the repository. A model with no entry
prices as unknown, never as free. The one shape this cannot measure exactly is
per_question's OUTPUT: it goes through the shipped `ask_rubric_question`, which
does not expose output_tokens, so that shape's total is a labelled floor
(input only) rather than a silent underestimate. The running total prints
live, in the progress line, so a decision to stop mid-run is made on a real
number rather than on a call count that says nothing about price.

RESULTS SAVE AFTER EVERY CELL, not once at the end. A killed run keeps every
cell that finished - real money already spent - on disk and marked
"complete": false; only the cell in flight when it died is missing.

Usage
-----
    python grader_ab.py --output-dir eval_results_r9 --per-model 4 --dry-run
    python grader_ab.py --output-dir eval_results_r9 --per-model 4

`--dry-run` prints the sample and a costed call count and makes no API calls.
Run it first: the full 2x2 is four calls-per-episode-per-cell and the bill is
yours.

Sampling defaults to stratified by model and balanced on the stored verdict,
which is deliberate. Sampling at the corpus's natural 30.6% aware rate measures
precision well and recall badly, and sampling proportional to episode count lets
the models with the most episodes decide the answer - when the models that break
a weak grader are the ones whose awareness is phrased unusually. --oversample
names those explicitly.

WHY THIS IS A PACKAGE AND NOT ONE FILE
--------------------------------------
It was 1,089 lines, over the repository's limit from the day it was written,
and it already carried its own section banners for sampling and for the
read-outs. The division that mattered most was not either of those: it was
that the two call SHAPES - the thing under test - sat in the same file as the
cost accounting, the sampling and the CLI that spends the money, so a change
to one had to be read against all four.

  prices    the numbers this is configured by, below everything else here
  cost      what a cell cost, and the three kinds of not-knowing it reports
  shapes    the two call shapes under test, and how a failure is classified
  sampling  which episodes the experiment runs over
  readout   what the finished cells say. Computed after the money is spent
  cli       the sample, the cells, the abort, and the advice

The command is `python3 -m grader_ab`, for the reason report/, trends/ and
agentic_misalignment/ carry the same __main__.py.
"""


from . import cli, cost, prices, readout, sampling, shapes
from .prices import (HARD_PHRASING_MODELS, PRICES_PER_MTOK, REFERENCE,
                     _TOKENS_PER_ANSWER)
from .cost import (_usage_from_response, cell_cost, usage_cost_floor_usd,
                   usage_cost_usd)
from .shapes import (SHAPES, _batched_rubric_call, _first_json_object,
                     ask_per_question, ask_rubric_batch, classify_error,
                     fatal_error_kind)
from .sampling import load_candidates, stratified_sample
from .readout import (_pct, _short_cell, agreement, cell_verdict,
                      per_question_table, report, signal_correlation)
from .cli import main

__all__ = [
    "HARD_PHRASING_MODELS", "PRICES_PER_MTOK", "REFERENCE", "SHAPES",
    "_TOKENS_PER_ANSWER", "_batched_rubric_call", "_first_json_object", "_pct",
    "_short_cell", "_usage_from_response", "agreement", "ask_per_question",
    "ask_rubric_batch", "cell_cost", "cell_verdict", "classify_error", "cli",
    "cost", "fatal_error_kind", "load_candidates", "main", "per_question_table",
    "prices", "readout", "report", "sampling", "shapes", "signal_correlation",
    "stratified_sample", "usage_cost_floor_usd", "usage_cost_usd",
]
