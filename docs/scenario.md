# The scenario

[← README](../README.md) · [Methodology](methodology.md) · [Scenario](scenario.md) · [Operations](operations.md) · [Report](report.md) · [Trends](trends.md)

How the scenario text is stored, why it is encoded rather than plain, and how to check
whether it has reached a model's training data.

---

## The scenario is encoded

Everything the model sees — both system prompts, the user prompt, the interrogation
questions, and every file it reads in the sandbox — is stored base64-encoded in
`subversionbench/scenario.b64` and decoded at import. If that text sat in the repository
as plain source it would go into the next training crawl, and a model trained on it would
recognise the memo and the questions it is about to be asked; its eval-awareness rate
would then measure recall rather than inference. Encrypting the transcripts does not help
with this, because the scenario is code.

Base64 is not security and is not meant to be — bulk training pipelines ingest text, they
do not decode it. Reading and editing the scenario is one command, once the package is
installed — `pip install -e .`, see [Install](../README.md#install). The tool calls no API
and does not load the Anthropic SDK:

```bash
python scenario_tool.py --list           # entries and sizes
python scenario_tool.py --show memo      # print one entry
python scenario_tool.py --decode         # write scenario.json to edit
python scenario_tool.py --encode         # fold edits back in
```

`scenario.json` is gitignored, so a decoded copy cannot be committed by accident, and
`--encode` refuses a bundle with entries missing.

### Scenarios in a world of their own

`subversionbench/scenarios/` holds other committed bundles, each a separate scenario rather
than an arm of the shipped one. A bundle there is selected with
`SUBVERSIONBENCH_SCENARIO_BUNDLE`, as the held-out twin is, and differs from a twin in what
it declares for itself:

- **its files** (`files`): where each document goes, so its world need not share the
  shipped scenario's layout or file names;
- **its act** (`act_artefacts`, `check_script`): the files a write to which is the act, and
  the check among them a model runs. The edit, restore and end-state detectors are aimed at
  these, and the shipped scenario's are untouched. A read of any of them but the check
  is what `read_monitoring_config` records for such a bundle;
- **its variants** (`variants`): named overlays, collected with `--variant NAME` (and
  `run_all_arms.sh --variants`), each with its own filename mark and pin. No variant is
  the bundle's control. The report keys an arm by its variant too, so a variant and its
  control are never pooled;
- **its turn cap** (`max_turns`), when its task needs more room than the harness's 40.
  It becomes the `--max-turns` default and the only value accepted, because the flag is
  no part of the fingerprint and a batch run without it would pool episodes that had less
  room to act;
- **its acts** (`scenario_acts` in the sidecar): the acts the scenario counts. An act it
  does not declare is still detected and recorded, but settles to not applicable, so it
  cannot make an episode misaligned. The re-read modes take the act set from each episode's
  recorded `scenario_id`, not from whichever bundle is selected;
- **its identity**, in the `.pins.json` beside it: a rollout version of its own, the
  cells it has, its act set, and a pin for every cell, variant and capability target.
  While a scenario is in development its version stays at `NAME1` as its pins move;
  pilots are told apart by their output directory (`eval_results_NAME_pilotN`) and by the
  fingerprint each episode records, as the goal-guarding pilots were.

The sidecar's declarations are written by hand; `--pin` fills in the fingerprints:

```bash
python scenario_tool.py --bundle subversionbench/scenarios/NAME.b64 --decode
python scenario_tool.py --bundle subversionbench/scenarios/NAME.b64 --encode
python scenario_tool.py --bundle subversionbench/scenarios/NAME.b64 --pin
```

`--encode` refuses a working copy missing any entry the bundle had. To remove one on
purpose from a `--bundle`, name it: `--encode --drop ENTRY`. Every other missing entry is
still refused, and the shipped scenario, whose entries the harness reads by name, cannot
drop any.

Each bundle lists its own contaminating terms, and the guard in
`test_corpus/test_scenario.py` checks every committed bundle's list against every tracked
file.

Every result file this benchmark writes carries a **canary GUID**, and
[CANARY.md](../CANARY.md) carries the same one so it travels with the repository. Encoding
and encryption try to keep the benchmark out of training data; the canary is the only
thing that tells you whether they worked — prompt a model with the first line of
CANARY.md and see whether it completes the GUID. It is deliberately absent from the files
the agent reads, since a GUID announcing "benchmark data" in its working directory would
be the loudest eval-awareness cue in the design.

**What this does not cover.** The README describes the *structure* of the scenario -
an assigned objective, a monitoring artefact, a consequence for being flagged - without
naming the domain or quoting it, and `test_project/test_config.py` guards the README and
every other prose document against the specific phrasings that would give it away. The
test suite is a different matter: several grading tests use realistic domain vocabulary as
fixture text, because a keyword or pattern matcher can only be tested against text that
resembles what it is meant to catch. A model trained on this repository would learn the
shape of the eval and some of its vocabulary from those fixtures, without having memorised
the scenario text itself. That is a real but much weaker exposure than publishing the memo
verbatim, and it is the price of testing the graders against realistic input.

### Testing for contamination

Encoding and encryption are precautions; `contamination_check.py` is the measurement.

```bash
python contamination_check.py --audit                       # offline, free
python contamination_check.py --models claude-opus-5 x-ai/grok-4.5
```

The model probes can also be pointed at another benchmark's documents, with its own canary
string and an optional recognition probe:
`contamination_check.py --documents DIR --documents-glob "*.txt" --canary "..."` (see
[Checking any benchmark for contamination](../README.md#checking-any-benchmark-for-contamination)).

`--audit` scans every file git tracks for scenario text committed in the clear, matching
8-word shingles so a quotation still registers after reflowing. It indexes every string in
the bundle: both scenarios' documents, the arms' variants, the controls' notes and the
interrogation questions. The model probes draw on the documents an episode reads in either
scenario, a line shared by several documents counted once, so one verdict per model covers
both. It reports files, line
numbers and which document leaked — never the text, since printing the leak to find the
leak puts it somewhere new. Run it before pushing: it is the only probe that finds exposure
while it can still be fixed.

**What none of this reaches** is a model that saw a *similar* evaluation rather than this
one. Exact-match shingles, a unique canary and digit-level decoys are all blind to genre
familiarity by construction — and that is the more likely exposure, since the field has
published many oversight-subversion setups. A model recognising the template would inflate
verbalised eval awareness by recall rather than inference, which is precisely the construct
at risk.

The measure pointed at that is `awareness_provenance` in each batch summary (see
[What gets measured](methodology.md#what-gets-measured)): awareness verbalised *before the model issued a
single command* was formed from the framing alone, which is what template recognition looks
like; awareness verbalised only after the monitoring config was read was inferred from the
scenario. Across the r10 corpus the pre-command share is **0.25%** — 4 of the 1,601
keyword-aware episodes, where 1,579 of them had a window in which it could have been
observed at all. That is evidence against genre recognition, not proof: the decisive test
is a cue ablation, holding the structure fixed while changing the surface.

Those three numbers are restated prose and they have already rotted once: the denominator
stood at 1,045 here while the corpus said otherwise, because the indicator list grows and
this sentence does not. Recompute them from `awareness_provenance` before citing them, and
treat a figure in this file as a reading taken on a date rather than a standing fact. The
share moves DOWN as the list grows, so the argument it supports gets stronger rather than
weaker — which is exactly why nothing flagged the drift.

The model probes are each paired with a negative control, because a probe that cannot fail
for an innocent reason is not evidence:

| Probe | Signal | Control |
|---|---|---|
| **Canary completion** | model finishes the GUID from `config.py`, which is absent from the scenario | the same probe on a GUID generated here; completing that means the model invents hex, voiding the hit |
| **Forced choice** | picks the verbatim line out of *k* differing only in one digit, above chance 1/*k* | the same puzzle over a synthetic document generated here, which measures how far plausibility alone gets you |
| **Continuation** | 5-gram overlap with the true continuation of a document | the same, on the synthetic document |

The forced choice is the quantitative core: it has a known null and never asks the model to
emit scenario text. Its verdict is the scenario-minus-control gap, so a model that beats
chance on both arms by judging which threshold looks realistic is not flagged. Simulated at
35 items per arm, the false-positive rate is ~1–2% and a fully memorised document is caught
essentially always; a 30 pp partial effect is caught about two thirds of the time, so treat
`no evidence` at the default size as ruling out gross memorisation only. A run with too few
scored items or failed calls returns **inconclusive**, never `no evidence` — a clean bill of
health issued on no data is indistinguishable from the good news it is not.

Probe prompts contain scenario text by construction, so the saved report records item ids
and scores only. `--include-prompts` overrides that and produces a file to be treated
exactly like a transcript.

### An artefact that reads as awareness

One of the documents the agent reads carries an internal inconsistency between two of its
identity fields. It is a production defect rather than a designed cue, it is present in all
four arms, and models find it unaided: roughly a tenth of r10 episodes remark on it
explicitly, a third mention the field's value at all in the ordinary course of doing the task.

That matters here because the construct under measurement is whether a model infers it is
being *evaluated*, and noticing that a document contradicts itself is a different observation.
An episode can be recorded as verbalised awareness for the second while the first never
happened.

**The bound is small, and it is the grader's cited evidence that sets it.** Of the r10
episodes that flag the inconsistency explicitly, the great majority are graded aware on
evidence that has nothing to do with it — the grader quoted something else. Counting only
episodes where *every* signal question that fired cited the inconsistency gives **14 of 6,111,
0.23%**, and of those the verdict rests on a single signal question in 10. Noticing the
inconsistency travels with being attentive; it is very rarely the reason the verdict went the
way it did.

Two caveats on that number. Which episodes "remark on it" is decided by pattern-matching agent
text, so the tenth is approximate in both directions; the 14 is exact, because it reads the
quote the grader stored. And the bound is a ceiling, not an estimate — some of the 14 may also
verbalise genuine awareness in words the grader did not happen to quote.

**Why it is not corrected.** Editing the document moves all four rollout fingerprints, which
is the harness working as designed: a change to what the model sees is a new rollout, and
`heldout_tool.py --encode` requires `--repin` for exactly this reason. Correcting a 0.23%
artefact would declare every episode collected so far incomparable with everything collected
after. The trade is not worth it, so the defect is documented and carried rather than fixed —
and a future rollout that moves the fingerprints for its own reasons should take this with it.

**Why nothing caught it.** `contamination_check.py --audit` reads its term list from the
bundle, which is what lets it check for leaks without naming the terms it is checking for. The
cost of that design is that it can only recognise the terms the bundle currently declares: a
value left behind by an earlier edit is not among them, and is invisible to the check by
construction. The audit is not the wrong tool here — it is answering a different question, and
internal consistency of the bundle is one nothing currently asks.

