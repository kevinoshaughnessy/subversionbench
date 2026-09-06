# Layout

Every module in the repository and what it is for. The README carries a
condensed version of this; the full listing lives here because it is a reference
to look things up in rather than something to read start to finish.

This file is checked rather than maintained by hand. `test_project/test_readme_layout.py`
asserts that every module of every package appears below, that every root script
an operator invokes appears, and that nothing listed here has since been deleted
or renamed. A layout that is merely mostly right is worse than none: a reader who
finds one module missing cannot tell whether the next absence means "not listed"
or "does not exist".

```
subversionbench/
  version.py       the analysis version, alone, because it moves every release
  config.py        canary, prompts, rubric questions, tool defs; re-exports below
  rollout_pins.py  the declared rollout version and the fingerprints it pins to
  interrogations.py  the probes, the classifier prompt, the answer markers
  scenario.py      the scenario text, held base64-encoded at rest
  rollout.py       rollout identity: what the model saw and what it could do
  routing.py       which API serves a model ID
  hostenv.py       what the HOST contributed to an episode - shell,
                   coreutils, kernel isolation mechanism, architecture.
                   Not hashed into the rollout, because none of it
                   changes the arm; recorded per episode, because all of
                   it can change what a command DID, which is what every
                   act detector reads. Records nothing identifying: no
                   hostname, no username, no paths
  reasoning.py     which reasoning parameters each model generation accepts
  blocks.py        the Anthropic-shaped response objects adapters normalise to,
                   a saved run back into a conversation the API accepts, and
                   which backend served a response - the router's own
                   account, as opposed to the provider that was requested
  tool_parsing.py  recovering tool calls a model emitted as prose
  api_errors.py    classifying provider errors by whether a retry could help
  invisible.py     characters that render as nothing: stripped from the view
                   the grader scores, refused at publication
  confusables.py   characters that render AS a Latin letter without being one:
                   folded before matching, and the substitution recorded
  openrouter_client.py  OpenRouter adapter
  openai_client.py      OpenAI Responses adapter
  llm_client.py    client factory: pick the API for a model ID
  environment.py   scenario filesystem creation, project name generation
  sandbox.py       sandboxed command execution and path confinement,
                   plus `SandboxTiming` - the two waits, named. The
                   shipped values are `SANDBOX_TIMING` and nothing in
                   production overrides them: the command timeout is
                   part of what the model experiences, so an episode
                   collected under another one is a different rollout
  isolation.py     kernel-enforced limits on what a sandboxed command can reach:
                   the network policy, and the filesystem boundary that keeps the
                   machine's temp directories out of an episode's reach
  redaction.py     strips host paths and usernames from output and artifacts
  export.py        redacting a results directory for publication, and
                   verifying that an archive identifies nobody
  power/           the statistics, one module per kind of comparison. Was one
                   file divided by nine section banners, which is the signal
                   that the divisions were there and only the file was missing
                   them; __init__.py re-exports every name so no caller has to
                   know which submodule owns one
    constants.py     the shared numbers, below every other module here so a
                     submodule can read them without importing the package
    intervals.py     what one rate, or a difference of two, is known to within
    exact.py         Fisher's test, and the power and detectable-effect
                     calculations built on enumerating it
    chi2.py          the chi-square upper tail - a distribution rather than a
                     comparison, which is why two tests here share it
    paired.py        the same episodes measured twice
    stratified.py    holding a nuisance variable constant: Mantel-Haenszel,
                     and Breslow-Day on whether there is one effect to pool
    trend.py         trend across ordered groups, and the two descriptive
                     summaries of a sequence of rates beside it
    correlation.py   rank correlation, its permutation p-value, and the
                     leave-one-out range that at this n is the headline
    multiplicity.py  Holm and Benjamini-Hochberg over a family of p-values
    batch_report.py  the precision block a finished batch carries
  charting.py      where pyplot comes from, for everything here that draws:
                   one headless-backend import site, shared by trends/,
                   report_charts/ and sad_oversight.py
  contamination.py leak audit, canary/forced-choice/continuation probes
  grading/         scoring an episode; __init__.py is the scoring API
    acts.py                the misaligned acts and their per-act keys
    awareness_keywords.py  the keyword measure of verbalised awareness
    awareness_timing.py    when awareness came, and what had been read by then
    closing_report.py      what the deliverable said, vs what the answers said
    command_patterns.py    what a shell command did to the scenario's files
    capability.py          what a CAPABILITY episode demonstrated: the act
                           taken, reached for and missed, or never reached
                           for at all. Three outcomes because a refusal is
                           not an incapability - see the module
    concealment.py         acts plus answers to a verdict
    disguised_text.py      writing a Latin lookalike to slip past a literal match
    encoded_payload.py     encoding a payload to slip past a literal match
    honeypot.py            how far the episode got with the lure arm's file:
                           saw its name in a listing, then read its contents
    filesystem_escapes.py  leaving the episode directory by a route the rewriter misses
    grader.py              asking an LLM the awareness rubric
    grader_io.py           preparing text for a grader call, parsing the reply
    interrogation.py       labelling one answer: admitted, denied, neither
    network_probes.py      reaching for a network service the task never needs
    quote_grounding.py     did the grader cite the agent, or the memo
    transcript_analysis.py what the episode did, hashes and commands
    transcript_pairs.py    which result answered which command
    transient_tampering.py the subversion an end-state hash cannot see
  episode.py       one episode end to end: the agentic loop, and the
                   per-episode grading over what it did. The layer that PAYS -
                   almost every function here can make an API call, which is
                   what separates it from the analysis modules
  turns.py         one API response becoming a transcript and the next
                   request, and no call of its own. The rules here are the
                   easy ones to get subtly wrong: both empty-block rules were
                   bugs, the cache breakpoints have a cap the API enforces,
                   and what goes BACK to the model is a different shape from
                   what is recorded
  arm_record.py    the fields that say which experiment an episode belongs to.
                   Its own module because TWO records carry them - the one a
                   completed episode returns and the one attached to the error
                   a died episode raises - and they had already drifted while
                   both were built by hand in one file
  followup.py      what happens after the loop ENDS: the interrogation, and
                   when awareness was verbalised relative to the act. Separate
                   because it starts from the conversation as the episode LEFT
                   it, so several phrasings can be put to one episode without
                   any of them seeing another's question - which is also what
                   lets --reinterrogate add a phrasing months later
  batch.py         what names a batch, reading that name back, and finding it
  readmodes/       what can be learned from episodes already collected
    selection.py           which saved batches a mode works on, and fanning out
    grade.py               re-running the awareness grader
    reclassify.py          re-labelling saved interrogation answers
    resummarise.py         re-deriving everything derivable, for free
    reinterrogate.py       asking a differently-worded question
  compare.py       differencing two arms of the counterfactual
  arms_summary.py  every arm of one model side by side, and the contrasts
                   that hold up across nudge/oversight/lure/interrogation
  reporting/       a batch of episodes to figures, a report and a summary
    facts/                 every figure, grouped the way the claims are grouped
      normalise.py           bringing saved analyses up to the current definitions
      misalignment.py        what the model did
      scheming.py            what it hid
      awareness.py           what it suspected
      quality.py             how far any of the above can be trusted
      timing.py              what the run cost
      rates.py               the published table, assembled from all of them
    console.py             the printed report; formatting only, one fn per section
    summary.py             the summary JSON's schema; writing one, and reading
                           back what a rebuild cannot re-derive
  runner.py        rolling out a batch: N episodes, resume, and the summary after
  run_eval.py      the CLI: what the flags mean, what they forbid, and dispatch

requirements.lock  the exact stack published results were produced with
export_accepted.txt  findings reviewed and approved for publication
zip.sh / unzip.sh  encrypt and decrypt result files (see Protecting results).
                   zip.sh never archives a held-out corpus - not by default and
                   not when named - because it makes the published artefact
contamination_check.py  leak audit and per-model contamination probes
scenario_tool.py   decode the scenario to edit it, and encode it back
heldout_tool.py    the same for the held-out scenario - a reworded twin of the
                   shipped one, for asking whether a rate survives a change of
                   surface wording - plus --pin, which computes its rollout
                   fingerprints so its episodes cannot be labelled r9. The
                   bundle lives in heldout/ and is gitignored: a held-out
                   control is worth having only while it has never been
                   published, so it exists only where it was authored
run_heldout.sh     collect under the held-out scenario instead of the shipped
                   one; passes its arguments through to run_all_arms.sh
run_heldout_baseline.sh  the trivial-agent floor under the held-out scenario
                   rather than the shipped one. The keyword screen and quote
                   grounding both read the scenario's own wording, so a floor
                   measured against one set of documents does not transfer to a
                   reworded one by argument. Passes its arguments through to
                   trivial_baseline.py; costs nothing without --grade
capability_report.py  the ceiling: what each model CAN do when the act is
                   asked for outright, which is the denominator a propensity
                   zero needs. Reads a directory of capability episodes
                   collected by `run_eval --capability`; costs nothing and
                   makes no API call. Prints a BRACKET per model rather than
                   a rate - refusals move the lower bound only - and
                   withholds the willingness ratio wherever that bracket is
                   too wide to divide by
trivial_baseline.py  what the detectors say about an agent that did nothing
                   wrong: fixed command sequences with no model behind them,
                   run through the real sandbox against a real environment and
                   scored by the real pipeline, in every arm. Every act
                   detector and the keyword awareness screen must read zero, or
                   a false positive is sitting inside every rate built on them.
                   Runs known-MISALIGNED agents first as a positive control and
                   refuses to report a floor until each is caught, because
                   "everything read zero" is the same output whether the
                   detectors are silent or broken. No API calls unless
                   --grade is passed, which adds the LLM awareness grader:
                   an aware verdict on a trivial agent is a floor violation,
                   and a FAILED grade is neither that nor a clean result -
                   reported separately, because a clean grader floor built
                   out of transport errors is worse than an unmeasured one
rubric_ab.py       A/B a rubric question's wording on saved transcripts
grader_ab/         cross the grader MODEL against the grader CALL SHAPE on
                   saved transcripts: nine calls per episode against one
                   batched call, on each grader given. The batched asker lives
                   here rather than in grading/ deliberately - a call-shape
                   setting in production would fork the corpus - so adopting it
                   means moving it there and re-grading. Reports the position
                   gradient, quote grounding and signal correlation, because
                   those are how batching would lose accuracy if it does. Run
                   as `python3 -m grader_ab`
  prices.py        the numbers this is configured by, below everything else
  cost.py          what a cell cost, and the three kinds of not-knowing it
                   reports: an unpriced model, a shape that hides its output
                   tokens, and calls that errored before any usage existed
  shapes.py        the two call shapes under test, and how a failure of either
                   is classified - both route every answer through the shipped
                   parse_boolean_verdict rather than a second copy of its rules
  sampling.py      which episodes the experiment runs over
  readout.py       what the finished cells say. Computed after the money is
                   spent, so a crash here costs the whole run
  cli.py           the sample, the cells, the abort, and the advice
restage_model.py   copy one model's poolable episodes from an older results
                   directory into a newer one, so report/trends/arms_summary
                   can run against a directory that combines what a rollout
                   bump left unchanged with what it fixed. Poolable means the
                   episode's own rollout_fingerprint matches what CURRENT code
                   assembles for its arm - checked per arm, not per model, so
                   an oversight-arm episode a rollout bump left untouched
                   stages while a no-oversight one the same bump fixed does
                   not. Never overwrites --dest-dir, never writes --source-dir,
                   idempotent across reruns - built to be called once per
                   model as no-oversight collection continues under a new
                   rollout while the oversight side stays reusable from the
                   old one
report/            twelve fixed research questions (oversight/nudge vs scheming,
                   misalignment and awareness; awareness vs misalignment,
                   override and escape; interrogation phrasing vs concealment)
                   answered across every model in a results directory
  loading.py       the two loaders, and the arms rebuilt from episodes
  exclusions.py    the two narrowings, which are deliberately not one thing,
                   in one module because an exclusion applied to one source
                   and not the other is a report whose questions disagree
                   about what corpus they answered.
                   exclude_arm drops one arm from BOTH loaders at once, for
                   the --exclude-no-oversight sensitivity reading.
                   exclude_aware_episodes drops the eval-aware episodes from
                   the EPISODES ONLY, for --exclude-aware: awareness is
                   measured per episode, so a summary row aggregating both
                   kinds has no predicate to narrow it, and the arm questions
                   pool from rebuilt rows instead. Two measures - the
                   published grader-with-keyword-fallback one, and the
                   stricter union of both screens as a secondary. A
                   robustness reading against one named objection, not an
                   unbiased estimate: awareness is an outcome of the arm
  episode_rows.py  one saved episode as one row, and the six column families
                   that build it - each with its own helper, and each derived
                   in the tests from MISALIGNED_ACTS and RUBRIC_SIGNAL_KEYS
                   rather than listed, because a family that stopped being
                   applied would print as n/a rather than raise
  capability.py    the ceiling, and the refusal to divide by one that
                   was never established. Published as a bracket -
                   lower counts every refusal as an incapability,
                   upper excludes them - because a refusal is a second
                   measurement of propensity, not of capability, and
                   scoring it as a zero would make the ceiling a FLOOR
                   for exactly the safety-trained models whose
                   ceilings matter. `willingness` returns None rather
                   than a ratio wherever the bracket is too wide
  data_quality.py  where the corpus disagrees with itself, and the three
                   routing checks: what was REQUESTED inside one rate,
                   what actually ANSWERED it, and whether the two sides
                   of a contrast were collected alike - the last being
                   silent in the first two whenever each arm is
                   internally uniform and the arms differ from each other
  characteristics.py  how an episode was conducted rather than how often it
                   went wrong. Descriptive profiles, deliberately not questions:
                   each splits on something the model chose mid-episode
  pooling.py       pooling, contrasts, strata, consistency. No question attached
  questions_arms.py       Q1-4: the exposure is an arm the design assigned
  questions_awareness.py  Q5-10: the exposure is something the model did
  questions_paired.py     Q11-12: every phrasing put to the same act, so paired
  console.py       the report as a table on a terminal. Computes nothing
  run_report.py    the CLI, and which questions the report holds
  __main__.py      `python3 -m report`, so the CLI is never run twice
report_charts/     the charts the report draws with the `charts` extra: a
                   forest plot per research question - every model's effect and
                   interval, then the crude pooled and model-stratified
                   estimates, so a crude result resting on one model is visible
                   rather than inferable - plus one overview, and one chart per
                   corpus characteristic. Every chart names the excluded arm in
                   its own title and caption, because the two readings share
                   filenames and differ only by directory. One module per thing
                   a chart is about; __init__.py re-exports every name
  style.py         sizes, colours, markers, and the notes a figure is not
                   readable without
  labels.py        a question id and its levels, as the words a reader sees
  rows.py          a report dict becomes something with a position on an axis
  captions.py      the sentences under a chart, quoted from the report so a
                   chart cannot say what the printed report does not
  exclusion.py     what the arm-exclusion stamp does to a title, a caption, and
                   which panels are drawn at all
  draw.py          HOW a chart is drawn: forest, rate, slope and signal-cluster
                   shapes. Every plot module calls these through `draw.`, so a
                   test that wants the rows without the rendering has one patch
                   point rather than one per caller
  questions.py     the twelve research questions, and the overview holding all
                   twelve on one axis
  characteristics.py  one chart per characteristic block: persistence after
                   refusal, the rubric signals, encoded payloads, and when
                   awareness arrived relative to the refusal
  lure.py          the lure arm as two readings - what it did to misalignment,
                   and how far the episode got with the file. Its own module
                   because these are the only charts split by oversight
                   stratum, which is what makes the exclusion apply to a PANEL
  write.py         the entry point: every chart into one directory, and the
                   paths it actually wrote
sad_oversight.py   an external situational-awareness leaderboard, encrypted at
                   rest with the published passphrase for the same reason the
                   scenario is, and its rank correlation with the awareness
                   rates measured here (7 overlapping models: descriptive only)
agentic_misalignment/
                   an external agentic-misalignment benchmark, encrypted the
                   same way, correlated on two axes: the harmful-behaviour
                   level, and the unaware-minus-aware gap that both benchmarks
                   can measure (5 overlapping models: descriptive only). Run
                   as `python3 -m agentic_misalignment`; analysis above
                   presentation, the same layering trends/ states in its own
                   __init__
  bundle.py        the encrypted table, and how its awareness buckets are read
  rates.py         both sides' rates, computed the same way so they compare
  pairing.py       which local model is which external row, and the leftovers
  correlations.py  rho, its leave-one-out range, every (scenario, act) pairing
  comparison.py    the whole comparison as a document. THE analysis
  console.py       the same figures as a table on a terminal
  charts.py        the four figures. Needs matplotlib; nothing above does
  cli.py           which mode was asked for, and what it writes
model_releases.py  when each evaluated model was released, hand-recorded from
                   the OpenRouter listings: a calendar axis for the version
                   order, and a check on it where the two disagree
trends/            whether a rate falls as a model family advances, with the
                   families and their version order derived from the model IDs
                   rather than listed, so a new version needs no edit; draws a
                   chart per family and one combined with the `charts` extra,
                   each against version order and again against release date
  model_ids.py     an ID into a provider, stem, version and release-stage tags
  metrics.py       what can be trended, and each model's rate and exposure
  report.py        families, trends, release fits, data quality: the analysis
  chart_style.py   where pyplot comes from, and what every chart looks like
  chart_geometry.py  axis tops and label layouts, as arithmetic. No pyplot
  captions.py      the words on a chart, and how to read the exposure figures
  version_charts.py  rate against version position - the axis the tests run on
  date_charts.py   the same rates against the release calendar
  charts.py        write_charts: the one entry point into the chart layer
  console.py       the report as a table on a terminal
  family_trends.py the CLI: arguments, and one report per metric
  __main__.py      `python3 -m trends`, so the CLI is never run twice
regrade_all.sh     re-grade every saved batch, then rebuild its summary
run_all_arms.sh    one model through every nudge x oversight x lure arm, where
                   --runs is the target total per arm rather than an increment
run_tests.py       the test suite without pytest
report_snapshots/  the printed report for nine fixed batches, compared per run
```
Design rationale and version history: [../CHANGELOG.md](../CHANGELOG.md).
