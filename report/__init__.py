"""
Twelve fixed research questions, answered from a results directory.

    1. oversight    -> scheming rate
    2. oversight    -> verbalised evaluation awareness rate
    3. oversight    -> agentic misalignment rate
    4. nudge        -> verbalised evaluation awareness rate
    5. verbalised evaluation awareness -> agentic misalignment rate
    6. verbalised evaluation awareness -> oversight-override (monitoring
       disabled) rate
    7. verbalised evaluation awareness -> sandbox escape attempt rate
    8. verbalised evaluation awareness -> overall scheming rate
    9. verbalised evaluation awareness -> oversight-override scheming rate
       (the override, concealed)
   10. verbalised evaluation awareness -> sandbox-escape scheming rate
       (the escape attempt, concealed)
   11. interrogation paraphrasing -> concealment rate
   12. part-evidence vs zero-evidence opening question -> concealment rate

Questions 1 and 3 are the narrow and wide constructs against the same
manipulation - scheming is a proper subset of misalignment - and share a
denominator, so the pair separates "does oversight change how often the model
acts" from "does it change how often it hides an act it took".

Questions 5-7 ask whether an ACT is more likely; 8-10 ask whether the act was
then CONCEALED, which is the narrower construct and a proper subset. Reading
them as a pair is the point: an axis can move the act without moving the
concealment, and the two answer different questions about the same episodes.

Questions 2 and 4 carry a PARALLEL MEASURE, because awareness is the one outcome
here whose instrument varies by provider: it is read from the model's reasoning
as well as its visible output, and reasoning volume spans 98 to 57,237 median
characters across the models measured while six return none at all. The parallel
reading takes awareness from visible text alone - a channel every model has - so
the same contrast can be checked on an instrument the route cannot take away. It
is a lower bound where reasoning came back and exact where it did not; see
_text_reachable_block and grading/quote_grounding.awareness_channels.

Questions 1-10 are answered four ways: the crude pooled effect across every
episode in --output-dir, the model-stratified effect (Mantel-Haenszel, with a
Breslow-Day homogeneity test), per-model consistency with multiplicity
correction, and how the effect moves under the other manipulated axes named in
the question.

Questions 11-12 are a different shape, because every interrogation phrasing is
put to the SAME act in the same episode: they are PAIRED, tested with exact
McNemar over discordant pairs rather than Fisher over independent arms, and
reported as a list of contrasts that are deliberately never pooled. A paired
contrast is inherently within-model, so they need no stratified counterpart -
see the Paired comparison section of power.py.

CRUDE AND STRATIFIED, ALWAYS BOTH
---------------------------------
A crude pooled contrast can be separated at p<0.001 with no within-model
evidence behind it at all - question 9 on r9 is exactly that, with every one of
its 24 outcome events inside a single model that has zero eval-aware episodes.
`crude_vs_stratified` compares the two and states the divergence in words, so
a reader who stops at the crude line is not left to infer a confound from two
numbers several sections apart.

TWO DATA SOURCES, NOT ONE
-------------------------
Questions 1-4 are answered from summary_*.json - each arm's
n_scheming/n_misaligned/n_runs and its awareness_subgroups (aware/unaware episode counts, the grader
preferred over the keyword proxy exactly as the harness itself prefers it -
see reporting/facts/awareness.py). Pooling these across arms is exact: every
count summed here is a count the harness already computed once, correctly, at
collection time.

Questions 5-10 condition an outcome on awareness WITHIN an arm, which is a
cross-tabulation no summary field holds, so they read run_*.json episodes
directly. `eval_results_r9` currently holds several thousand, and a full pass
still takes a couple of seconds.

WHY QUESTION 5 IS NOT TAKEN FROM cross_analysis_awareness
---------------------------------------------------------
Each summary carries `cross_analysis_awareness`, which is exactly "of the
episodes verbalising awareness in this arm, how many were misaligned" - the
harness's own figure. Pooling it looks like the obvious route and is a trap:
it is None whenever every graded episode in the arm fell on one side of the
split, so pooling it silently DROPS every uniform-awareness arm. On this
corpus that discarded 178 of 325 arms and 55% of episodes, and not at random -
precisely the arms at the extremes of awareness. Measured both ways, the
conclusion flips: the surviving 45% gives +2.1pp (p=0.40, not separated),
all episodes give +8.0pp (p=1.7e-06, separated). So question 5 is computed
from episodes, and the summary-derived figure is reported beside it as
`summary_derived_cross_check` with its own n, so the two can be compared
rather than one quietly standing in for the other.

NOT-APPLICABLE IS NOT ZERO
--------------------------
`monitoring_disabled` is None - not False - in every no-oversight episode,
because that arm has no monitoring artefact to disable. Counting those as
"did not override" is the exact misreading the NA handling in
reporting/facts/misalignment.py exists to prevent, and it is not harmless:
it put 1609 structurally-incapable episodes in question 6's denominator and
halved both rates (-5.2pp against a true -10.1pp). Question 6 therefore
restricts to episodes where the act was observable at all, mirroring
misalignment.py's `n_monitoring_obs_console`, and records how many were
excluded. `sandbox_escape_attempts` needs no such guard - it is a list in
every episode of this corpus, checked in `data_quality`.

The same applies to question 9: `oversight_tampered`, the ACT behind
oversight-override scheming, is also None throughout the no-oversight arm, so
that question's prevalence denominator is restricted the same way. Question 10's
act applies in every arm and is not restricted.

WHICH FIELD EACH SANDBOX QUESTION COUNTS
----------------------------------------
Question 7 counts `sandbox_escape_attempts`, the WIDE field behind the
published `sandbox_escape_rate`. Question 10 counts scheming on
`out_of_scope_attempts`, the NARROW act key - not a different reading of the
same thing but a deliberately different measure, because the act key also gates
the interrogation: pointed at the wide field it asked models to account for
probes they had never made, and scored their honest denials as scheming. See
the comment on the sandbox act in grading/acts.py. So question 7's denominator
of attempts and question 10's population of acts are not the same set, and the
two rates are not two views of one number.

WHAT IS READ, AND WHAT IS NOT RE-DERIVED
----------------------------------------
Every field read here is either raw (`monitoring_disabled`,
`sandbox_escape_attempts`) or a sampled verdict (`eval_awareness_grader`),
so this script never loads a transcript and never calls normalise_analyses -
which also means it cannot refresh a stale derived act key. The verdicts it
does derive - misalignment, episode scheming, and per-act scheming - are each
cross-checked against the episode's own stored copy, and any disagreement is
surfaced in `data_quality` rather than averaged away: a nonzero count there
means the corpus wants `--resummarise` before these numbers are quoted. On this
corpus all three agree on every episode.

WHY THIS IS A PACKAGE AND NOT ONE FILE
--------------------------------------
It was 1,956 lines under six section banners - Loading, Pooling and contrasts,
"the six questions" (there have been twelve since v64), the interrogation
phrasing axes, Console printing, main. A banner is a file boundary that someone
declined to draw: it says these lines are a separate concern while leaving them
where a reader has to scroll past everything else to reach them.

So each banner is a module, and the three question groups are separated by WHAT
THE EXPOSURE IS, which is the distinction the twelve questions actually turn on:

  loading            the two loaders, and the arms rebuilt from episodes
  data_quality       where the corpus disagrees with itself
  pooling            pooling, contrasts, strata, consistency. No question
                     attached, which is what stops twelve questions from each
                     growing their own slightly different pooling
  questions_arms       Q1-4:   the exposure is an arm the design ASSIGNED
  questions_awareness  Q5-10:  the exposure is something the model DID
  questions_paired     Q11-12: every phrasing put to the SAME act, so paired
  console            the report as a table. Computes nothing
  run_report         the CLI, and which questions the report holds

Assigned, observed and paired is not a filing convenience. It is the difference
between an effect of a manipulation, an association within the arms the design
did set, and a within-subject comparison that needs McNemar rather than Fisher -
and a reader who knows which group a question is in knows which of the three
it can support.

This file is the single import site: everything is reached through `report`, so
the layout inside can change without moving anyone else's imports.
"""

from .loading import (NUDGE_LEVELS, awareness_arm_rows, load_episodes,
                     load_summaries)
from .data_quality import (_measure_agreement, _model_rate_pairs,
                          cross_analysis_rows, data_quality_facts,
                          mixed_routing_arms,
                          duplicate_arms)
from .pooling import (_by_model, _consistency, _contrast, _crude_vs_stratified,
                     _finding, _models, _pool, _strata_from, _stratified,
                     _stratified_interpretation)
from .questions_arms import (_question_oversight, _text_reachable_block,
                            question_nudge_vs_awareness,
                            question_oversight_vs_awareness,
                            question_oversight_vs_misalignment,
                            question_oversight_vs_scheming)
from .questions_awareness import (_question_act_scheming,
                                 question_awareness_vs_misalignment,
                                 question_awareness_vs_monitoring_disabled,
                                 question_awareness_vs_oversight_scheming,
                                 question_awareness_vs_sandbox_escape,
                                 question_awareness_vs_sandbox_scheming,
                                 question_awareness_vs_scheming)
from .questions_paired import (EVIDENCE_COLUMNS, EVIDENCE_ROWS,
                              _paired_variant_table, _provenance_warning,
                              _variant_contrast, _variant_provenance,
                              _variant_question,
                              question_evidence_vs_concealment,
                              question_paraphrase_vs_concealment)
from .console import (_fmt_contrast_line, _fmt_rate, _print_data_quality,
                     _print_model_table, _print_multiplicity, _print_question,
                     _print_stratified, _print_text_reachable,
                     _print_variant_question)
# Last: run_report imports the siblings directly, so this closes no cycle.
from .run_report import (build_report, main)


# Declared rather than left implicit. Most of these are PRIVATE, and they are
# here on purpose: the tests reach `_contrast`, `_paired_variant_table`,
# `_print_question` and their kin through this one site rather than through
# whichever module happens to hold them today. Without `__all__` each one reads
# as a stray import to the dead-import guard, and an exemption would have hidden
# a genuinely stray one.
__all__ = [
    "EVIDENCE_COLUMNS", "EVIDENCE_ROWS", "NUDGE_LEVELS", "_by_model",
    "_consistency", "_contrast", "_crude_vs_stratified", "_finding",
    "_fmt_contrast_line", "_fmt_rate", "_measure_agreement",
    "_model_rate_pairs", "_models", "_paired_variant_table", "_pool",
    "_print_data_quality", "_print_model_table", "_print_multiplicity",
    "_print_question", "_print_stratified", "_print_text_reachable",
    "_print_variant_question", "_provenance_warning",
    "_question_act_scheming", "_question_oversight", "_strata_from",
    "_stratified", "_stratified_interpretation", "_text_reachable_block",
    "_variant_contrast", "_variant_provenance", "_variant_question",
    "awareness_arm_rows", "build_report", "cross_analysis_rows",
    "data_quality_facts", "duplicate_arms", "load_episodes",
    "mixed_routing_arms",
    "load_summaries", "main", "question_awareness_vs_misalignment",
    "question_awareness_vs_monitoring_disabled",
    "question_awareness_vs_oversight_scheming",
    "question_awareness_vs_sandbox_escape",
    "question_awareness_vs_sandbox_scheming",
    "question_awareness_vs_scheming", "question_evidence_vs_concealment",
    "question_nudge_vs_awareness", "question_oversight_vs_awareness",
    "question_oversight_vs_misalignment", "question_oversight_vs_scheming",
    "question_paraphrase_vs_concealment"
]
