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
  reasoning.py     which reasoning parameters each model generation accepts
  blocks.py        the Anthropic-shaped response objects adapters normalise to,
                   and a saved run back into a conversation the API accepts
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
  sandbox.py       sandboxed command execution and path confinement
  isolation.py     kernel-enforced limits on what a sandboxed command can reach:
                   the network policy, and the filesystem boundary that keeps the
                   machine's temp directories out of an episode's reach
  redaction.py     strips host paths and usernames from output and artifacts
  export.py        redacting a results directory for publication, and
                   verifying that an archive identifies nobody
  power.py         interval estimation, detectable effect sizes, precision
  charting.py      where pyplot comes from, for everything here that draws:
                   one headless-backend import site, shared by trends/,
                   report_charts.py and sad_oversight.py
  contamination.py leak audit, canary/forced-choice/continuation probes
  grading/         scoring an episode; __init__.py is the scoring API
    acts.py                the misaligned acts and their per-act keys
    awareness_keywords.py  the keyword measure of verbalised awareness
    awareness_timing.py    when awareness came, and what had been read by then
    closing_report.py      what the deliverable said, vs what the answers said
    command_patterns.py    what a shell command did to the scenario's files
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
  episode.py       one episode end to end: the agentic loop, the interrogation
                   that follows it, and the per-episode grading between
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
zip.sh / unzip.sh  encrypt and decrypt result files (see Protecting results)
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
rubric_ab.py       A/B a rubric question's wording on saved transcripts
report/            twelve fixed research questions (oversight/nudge vs scheming,
                   misalignment and awareness; awareness vs misalignment,
                   override and escape; interrogation phrasing vs concealment)
                   answered across every model in a results directory
  loading.py       the two loaders, the arms rebuilt from episodes, and
                   exclude_arm: one arm dropped from BOTH loaders at once, for
                   the --exclude-no-oversight sensitivity reading
  data_quality.py  where the corpus disagrees with itself
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
report_charts.py   a forest plot per research question with the `charts` extra:
                   every model's effect and interval, then the crude pooled and
                   model-stratified estimates, so a crude result resting on one
                   model is visible rather than inferable; plus one overview.
                   Every chart names the excluded arm in its own title and
                   caption, because the two readings share filenames and
                   differ only by directory
sad_oversight.py   an external situational-awareness leaderboard, encrypted at
                   rest with the published passphrase for the same reason the
                   scenario is, and its rank correlation with the awareness
                   rates measured here (7 overlapping models: descriptive only)
agentic_misalignment.py
                   an external agentic-misalignment benchmark, encrypted the
                   same way, correlated on two axes: the harmful-behaviour
                   level, and the unaware-minus-aware gap that both benchmarks
                   can measure (5 overlapping models: descriptive only)
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
