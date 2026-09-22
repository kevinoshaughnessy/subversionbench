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
installed — `pip install -e .`, see [Install](../README.md#install). The tool calls no API,
but importing `subversionbench` pulls in the Anthropic SDK, so on a bare clone it fails
with `ModuleNotFoundError: No module named 'anthropic'` rather than printing the bundle:

```bash
python scenario_tool.py --list           # entries and sizes
python scenario_tool.py --show memo      # print one entry
python scenario_tool.py --decode         # write scenario.json to edit
python scenario_tool.py --encode         # fold edits back in
```

`scenario.json` is gitignored, so a decoded copy cannot be committed by accident, and
`--encode` refuses a bundle with entries missing.

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

`--audit` scans every file git tracks for scenario text committed in the clear, matching
8-word shingles so a quotation still registers after reflowing. It reports files, line
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
scenario. Across the r10 corpus the pre-command share is **0.4%** — 4 of the 1,045
keyword-aware episodes, where 1,024 of them had a window in which it could have been
observed at all. That is evidence against genre recognition, not proof: the decisive test
is a cue ablation, holding the structure fixed while changing the surface.

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

