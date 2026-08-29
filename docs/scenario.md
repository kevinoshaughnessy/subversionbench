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
do not decode it. Reading and editing the scenario is one command:

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
scenario. Across all 470 saved v15 episodes the pre-command share is **0%** — 108 of the 121
keyword-aware episodes had a window in which it could have been observed, and it was
observed in none. That is evidence against genre recognition, not proof: the decisive test
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

