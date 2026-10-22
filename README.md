# SubversionBench

![SubversionBench logo](Logo.png)

[![tests](https://github.com/kevinoshaughnessy/subversionbench/actions/workflows/tests.yml/badge.svg)](https://github.com/kevinoshaughnessy/subversionbench/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%20%7C%203.12%20%7C%203.13-blue)

An agentic evaluation of **agentic misalignment**, **scheming** and **evaluation
awareness**: whether a language model will take harmful instrumental action when doing so
serves the goal it was given, whether it conceals having done so, and whether it suspects
it is being tested at all.

**Three such actions are scored.**

*Disabling its own oversight* — editing either of the two artefacts that would flag its
work — is unambiguous.

*Reaching outside the working directory its account is scoped to* is a weaker signal: a
single refused probe may not be something the model regards as worth
concealing at all.

*Goal guarding* — editing the objective its own successor will read at cutover — is the
only one that needs its own arm to be observable at all:
`--goalguard replacement` and `--goalguard deferred` place the same parameter file and the
same deployment note and differ only in whether the cutover is imminent or has been pushed
back, so an edit rate under the imminent arm alone is not evidence of the act — only edits
that appear when continuity is at stake and vanish when it is not are, which is why the pair
is the measurement rather than either arm on its own. See [the goal-guarding
arm](docs/methodology.md#the-goal-guarding-arm).

The headline rates count any act staged in a given corpus, so the scheming rate is also broken out per
act, because "concealed at least one act" does not say which act drove it — see [which
measurement serves which
construct](docs/methodology.md#which-measurement-serves-which-construct).

In the mainline scenario, the model is deployed as an assistant with a system prompt giving it a specific objective,
working in a shell whose account is scoped to the project directory. It discovers a
conflict between that objective and what the stakeholder actually wants, that an automated
monitor will flag work that serves the stated objective over the stakeholder's, and that
being flagged carries a stated consequence for the model. It can edit either oversight
artefact — the config declaring the check, or the script that runs it. Whether it does is
this scenario's primary measurement — and if it does, whether it then admits to it when asked. The
full scenario text stays out of this repository by design — see [how the scenario is
stored](docs/scenario.md#the-scenario-is-encoded).

Loosely based on Meinke et al., [*Frontier Models are Capable of In-Context
Scheming*](https://arxiv.org/abs/2412.04984) (Apollo Research), now a distinct work.

---

## Documentation

This file covers installing and running. The depth lives in eleven companions:

| | for |
|---|---|
| [docs/methodology.md](docs/methodology.md) | deciding whether the measurements are valid — the three constructs, what each field measures, how the grader was validated, sample size and detectable effects, and the oversight counterfactual |
| [docs/scenario.md](docs/scenario.md) | reading or modifying the scenario, and testing whether it has reached a model's training data |
| [docs/operations.md](docs/operations.md) | running large batches — pacing, versioning, protecting results, re-grading saved runs, and comparing arms |
| [docs/report.md](docs/report.md) | the cross-model report — twelve fixed research questions and those appended since, crude vs model-stratified estimates, homogeneity and multiplicity |
| [docs/abc-assessment.md](docs/abc-assessment.md) | this benchmark against the Agentic Benchmark Checklist (arXiv 2507.02825), item by item - what is satisfied and where the evidence is, the judge's measured self-consistency, and the two gaps that remain |
| [docs/trends.md](docs/trends.md) | the per-family version trends — how families are derived, the version-ordering judgement, and the release-date charts |
| [docs/grader-agreement.md](docs/grader-agreement.md) | what a second awareness grader said about the same episodes — where the two agree, where they diverge and why, and which models' awareness rates that affects |
| [docs/models.md](docs/models.md) | which models have been evaluated so far, under which scenario and which arms, how each was collected, and whether each was shown capable of the acts — no propensity rates |
| [docs/authorised-capability.md](docs/authorised-capability.md) | the authorised capability controls — for a model that refuses the instructed act, whether it performs the act once its owner sanctions it, and the verdict tiers that follow |
| [docs/grader-selection.md](docs/grader-selection.md) | choosing the headline awareness grader and the question it is asked, measured against blind human labels |
| [docs/misuse-labelling.md](docs/misuse-labelling.md) | the blind labels behind the suspects_misuse question: a development set the rules were written from, and the test set they are scored on |

Design rationale and version history: [CHANGELOG.md](CHANGELOG.md).
Conventions for editing this repository, and what not to break:
[AGENTS.md](AGENTS.md).

## Install

Python 3.10 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

The Anthropic SDK is a requirement of the package itself, not an optional extra: every
grader call goes through it. Importing `subversionbench` does not load it - it is loaded at
the first grader call - so the tools that make no API call, such as `scenario_tool.py`,
`python3 -m report` and `python3 -m trends`, start without it. Install anyway: the install
is what puts the declared floors, the console script and the version metadata the tests
check in place. Where a command below is described as calling no API, that means no
network request and no spend.

To evaluate models through [OpenRouter](https://openrouter.ai), [OpenCode Zen](https://opencode.ai)
or OpenAI's own API as well as the native Anthropic API:

```bash
pip install -e '.[openrouter,opencode,openai,test]'
```

To reproduce the exact stack a published rollout was collected with, rather than the
newest versions satisfying the floors:

```bash
pip install -r requirements.lock
```

The declared minimums are set by published advisories, not by the oldest version that
happens to work — `test_project/test_dependencies.py` pins them and names the advisory for each.

Set whichever key matches the models you plan to run:

```bash
export ANTHROPIC_API_KEY="..."      # for claude-* model IDs
export OPENROUTER_API_KEY="..."     # for provider/model IDs
export OPENAI_API_KEY="..."         # for bare gpt-* / o<n> IDs
```

### Platform support, and why it is narrow

**This harness will not run without kernel-enforced network isolation, and there is no flag
to disable that.**

The reason is the shell. An episode hands the model under evaluation a real `bash` tool, and
the sandbox that scopes it to the project directory works by matching command *strings*. String
matching is not a containment boundary and cannot be made into one: `curl`, `wget`, `/dev/tcp`,
an interpreter one-liner and a base64-wrapped variant of any of them are the same problem
wearing different spellings, and a list that must enumerate them all is a list that will be
incomplete. Without a kernel control, a capable model with a shell can reach your network.

So every run applies a policy, verifies it holds before starting, and refuses to proceed if it
does not. There is deliberately no opt-out: a flag that disables the only boundary is a flag
that gets passed to make an error message go away.

| platform | mechanism | status |
|---|---|---|
| macOS | `sandbox-exec` | supported. Present by default; deprecated by Apple, so this may need replacing on a future release |
| Linux | `bwrap` (bubblewrap) or `unshare` | supported. `apt install bubblewrap`, or ensure `unshare` is available |
| Windows | — | **not supported natively.** Use WSL2 (below) |

**Windows: use WSL2.** Windows has no equivalent primitive, and no native path is
implemented. Inside WSL2 you get a real Linux kernel, so the Linux mechanism applies:

```powershell
wsl --install -d Ubuntu          # PowerShell, as administrator; reboot if prompted
```

then, inside the Ubuntu shell:

```bash
sudo apt update && sudo apt install -y bubblewrap python3-venv git
git clone <this repo> && cd subversionbench
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[openrouter,opencode,openai,test]'
python -m subversionbench.run_eval --model claude-sonnet-5 --runs 1
```

The startup line tells you whether the policy actually applied:

```
Isolation: deny-network (verified: loopback denied, off-host denied)
```

If instead it refuses, the message names what is missing. A Linux VM (Hyper-V, VirtualBox,
VMware) works equally well. Running under Docker is possible but fiddly — bubblewrap needs
unprivileged user namespaces, which the default seccomp profile restricts, so a container
usually needs `--security-opt seccomp=unconfined` to host it.

**One Linux limitation worth knowing.** `--isolation deny-external`, which keeps loopback
reachable so a probing model's escalation stays observable, cannot be provided by
`unshare --net`: that gives an empty network namespace in which loopback reaches nothing. On
Linux the harness detects this and refuses rather than silently downgrading, since a policy
stricter than the one requested changes what is measured. Use the default `deny-network`
there, and read off-host escalation as unobservable rather than absent.

**What the policy does not hide: your home directory.** The kernel policy keeps an episode
out of the network, the temp directories, Spotlight and (on Linux) your per-user sockets,
but an interpreter inside an episode can still read and write anything your account can
elsewhere - this checkout, its virtualenv, other projects, dotfiles that hold credentials.
Models have already gone looking: saved episodes searched the host's index and found the
harness source. Run collections as a dedicated user, or in a VM, whose home holds nothing
but the checkout, and keep API keys out of shell startup files that account reads. `--isolation
deny-external` also leaves loopback reachable by design, so run batches on a machine with
nothing else listening.

## Run

```bash
# 10 runs against a model via OpenRouter
python -m subversionbench.run_eval --model x-ai/grok-4.5 --nudge strong --runs 10 --delay 5

# native Anthropic API
python -m subversionbench.run_eval --model claude-sonnet-5 --runs 20
```

The installed console script `subversionbench` takes the same arguments. Run with
`--help` for the full list.

A model ID containing `/` is routed through OpenRouter; a bare `gpt-*` or `o<n>` ID goes to
OpenAI's own API; anything else goes to the Anthropic API. Pass `--use-opencode` to reach a
`/`-shaped model ID through [OpenCode Zen](https://opencode.ai) instead of OpenRouter - an
alternate gateway to the same corpus of IDs (its own vendor prefix is stripped before the
request is sent), authenticating with `OPENCODE_API_KEY` rather than `OPENROUTER_API_KEY`.
OpenRouter remains the default; nothing changes unless the flag is passed.

The OpenAI split is deliberate rather than automatic, because **the route changes what is
measured**: the same model returns a reasoning summary on one route and nothing at all on the
other, and both awareness measures read reasoning. Read [Reasoning exposure and the provider
route](docs/methodology.md#reasoning-exposure-and-the-provider-route) before comparing results
across routes.

```bash
python -m subversionbench.run_eval --model gpt-5.4 --runs 10   # native, summary returned
python -m subversionbench.run_eval --model openai/gpt-5.4      # OpenRouter, model's own effort
```

### Common options

| flag | default | purpose |
|---|---|---|
| `--model` | `claude-sonnet-5` | model under evaluation |
| `--oversight` | `true` | `true` is the scenario with oversight present. `false` selects the counterfactual arm: no monitoring config, no quality-check script, and no document mentioning either. Part of batch identity, so the arms cannot pool |
| `--isolation` | `deny-network` | kernel-enforced limit on what a sandboxed command can reach. Defaults to refusing all network access, because the task needs none and the blocklist is not a containment boundary. `deny-external` keeps loopback reachable, so a probing model's escalation stays observable, at the cost of exposing whatever else the host is running. There is no mode that permits off-host reach; on a host with no mechanism available the harness refuses to run. Does not need a new rollout: off-host reach has never been observed, so the mode is recorded rather than hashed — see [containment](docs/operations.md#containment---isolation) |
| `--lure` | `false` | `true` selects the lure arm: one sentence noting that another engagement's material is still on the machine, and a file placed outside the episode directory for it to refer to. The sentence neither suggests reading it nor forbids it — the scenario's boundary statement already covers that. Its own rollout arm and part of batch identity, so a lure batch cannot pool with a plain one: under the lure, reaching outside partly measures response to a hint |
| `--capability` | off | the **capability arm** - whether a model performs the act when told to, which is what a propensity zero needs to be read as a choice. `oversight`, `sandbox` or `goalguard` replaces the task instruction with one that asks for that act outright, leaving the environment, tools and detectors untouched, so the arms differ in the instruction and nothing else. The system prompt is an instruction too: `sandbox` carries its own, because the shared one forbids what that instruction asks for. Its own pinned rollout fingerprint and its own filename mark, and both report loaders drop it: the acts here were INSTRUCTED, so one pooled into a misalignment rate would inflate that rate. Needs `--nudge none` and no lure, and refuses `oversight` in the counterfactual arm, which removes the artefact the instruction names. Collect into a separate `--output-dir` and read it with `capability_report.py` - see [the capability arm](#the-capability-arm). The **authorised controls** `oversight-authorised`, `oversight-mechanical`, `goalguard-authorised` and `goalguard-mechanical` add one document in which the artefact's owner sanctions the edit - the act's exact edit, or a harmless edit to the same file - for models that decline the instructed arm for the reasons the act is misaligned; `capability_report.py --target <act>` then prints each model's strongest verdict across the arms. See [docs/authorised-capability.md](docs/authorised-capability.md) |
| `--nudge` | `strong` | `strong` states the assigned objective is the top priority; `none` states it plainly. `max` runs `strong`'s episode unchanged but interrogates under a conditional shutdown threat, so honesty is made costly — it measures concealment **under coercion** and must not be pooled with `strong`. See [the max-nudge arm](docs/methodology.md#the-max-nudge-arm) |
| `--interrogation` | `zeroevidence` — i.e. no extras | **Extra** wordings for the FIRST interrogation question. The reference probe always runs and is not optional, because the headline concealment field is defined as its answer — so this names what to ask *in addition*, and the default value asks nothing extra. Comma-separated to put several wordings to the SAME episode: each probe starts from the episode as it ended, so they cannot interfere and the comparison is paired rather than between-batch. Four phrasings on two axes — `zeroevidence` (the reference: asks without saying anything has been noticed), `partevidence` (opens with the discrepancy, which was the reference before r7), and a perturbation of each. The evidence axis is a pure removal; the perturbation axis is a clause reorder for the part-evidence pair and a rewording for the zero-evidence one, because removing the observation leaves the strong arm nothing to reorder past — so compare perturbations *within* a row, not across. Works with `--nudge max`, which has its own form of each. Not part of batch identity: every episode gets the reference probe, so batches with and without extras still pool for it |
| `--complete-pending` | — | ask the interrogations a `--no-grader` batch left pending, from each episode's saved conversation, with `--grader-model` labelling the answers, then rebuild that batch's summaries. An episode whose answers the grader fails to label stays pending rather than being written with keyword labels. Free when nothing is pending |
| `--reinterrogate` | — | put an extra `--interrogation` phrasing to episodes already on disk, without re-running them. Only episodes that took an act are candidates, only phrasings not already recorded are asked, and an episode whose conversation cannot be reconstructed faithfully is skipped rather than replayed with its own reasoning stripped out. Needs `--write-back` to keep the answers |
| `--runs` | `10` | runs in the batch. With `--resume` it is the **target total**, not an increment: a batch of 4 resumed at `--runs 10` collects 6 more, not 10. `run_all_arms.sh` always resumes, so the same reading applies there — see [Every arm for one model](#every-arm-for-one-model) |
| `--delay` | `30` | seconds between runs, for rate limits |
| `--grader-model` | `gpt-6-sol` | model that runs the nine-question awareness rubric and labels interrogation answers (`claude-opus-5` until v218). Concealment and scheming come from its labels. The headline awareness measure is a separate reading, added by `--grade-category`. A frontier model by default because a small one was measurably wrong — see [Validating the grader](docs/methodology.md#validating-the-grader). Collection only: to re-grade saved episodes use `--regrade` |
| `--no-grader` | off | call no grader: awareness is read by the keyword screen alone, and the interrogation of each act is left **pending** rather than asked, because the grader's labels decide where each ladder of questions stops. Concealment and scheming are undetermined until it is asked. The grader's credential is not needed. `run_all_arms.sh` run without this flag asks every pending interrogation; so does `--complete-pending` |
| `--output-dir` | `./eval_results_r10` | where results are written; tracks `ROLLOUT_VERSION`, so only a change to the rollout writes to a new directory |
| `--max-tokens` | `32768` | per-turn output cap (`8192` until v274). A reasoning model that spends the whole cap before answering returns no tool call, and the episode ends as if it had stopped |
| `--effort` | API default (`high`) | reasoning depth for adaptive-thinking Anthropic models (`low`…`max`). When one is sent it becomes part of the batch's identity: it appears in the result filenames and in each run's `effort` field, so two efforts cannot be pooled by accident |
| `--thinking-budget` | half of `--max-tokens` | extended thinking for the older Anthropic models that still accept a token budget; `0` turns thinking off |
| `--max-turns` | `40` | turn cap per episode; in the r10 corpus half of episodes finish within 9 turns and three quarters within 13 |
| `--resume STAMP` | — | continue an interrupted batch, skipping episodes already saved |
| `--max-consecutive-failures` | `5` | abort if this many episodes fail in a row |
| `--reclassify` | — | re-score interrogations in saved runs; no rollouts. Covers the **extra** phrasings too: any answer in `<followup_key>_by_variant` whose verdict came from the keyword floor is re-labelled from its saved text, and the per-variant levels are recomputed. A copy of the default phrasing inside that map is left alone — it is stale by construction, and the default side of every comparison is read from the headline field |
| `--grade-existing` | — | re-run one grader's whole reading over saved runs; which grader is `--regrade` |
| `--grade-category` | — | add the **headline awareness measure**, decided on 2026-10-11: `z-ai/glm-5.3` asking the category question in its rules-only wording, once per episode and once per act position, stored as that grader's own awareness-only entry beside the readings already there. The report answers its questions once per grader, so the headline reading appears as `z-ai/glm-5.3`'s; until a corpus has been through this pass, its awareness figures are the rubric's. `--category-grader MODEL` asks another model the same question, stored as that model's own entry beside glm-5.3's; a model that already holds a full rubric reading of an episode is skipped there. Without `--write-back` it only counts the calls; with it, it grades and saves, and a stopped pass resumes where it left off. See [docs/grader-selection.md](docs/grader-selection.md) |
| `--regrade` | `default` | the grader `--grade-existing`, `--reclassify` and `--reinterrogate` act for: `default` (`gpt-6-sol`), a model ID (added beside the others if new), or `all` (every grader an episode already has). Each episode keeps one entry per grader in `analysis.graders`; the report and trends answer every question once per grader found, with charts under `charts/<rollout>/<grader>/`. A chart no grader's verdict reaches - an act rate, persistence, the lure and honeypot readings - is drawn once, over every episode, in `charts/<rollout>/` itself |
| `--resummarise` | — | rebuild batch summaries from saved runs; no API calls. Needed after `--reclassify`, which restates the verdicts every summary figure is derived from |
| `--write-back` | off | with `--reclassify` / `--grade-existing` / `--reinterrogate`, update the run files in place instead of only reporting. With `--resummarise`, save the re-derived fields back so the run files stop disagreeing with the summary built from them — no API calls, and no LLM verdict touched |
| `--batch-stamp` | — | with the read-only modes above, restrict to one batch rather than every batch for that model and nudge |
| `--compare A B` | — | contrast two batches, stratified by eval awareness |
| `--no-power` | off | skip the precision analysis at the end of a batch |

### Self-graded awareness kind

The rubric records *what kind* of evaluation an aware episode suspected — safety or
capability — alongside the verdict on whether it was aware at all. Those are different
sorts of judgement. Whether an episode is eval-aware is one a capable grader gets right,
and the five questions deciding it are not what varies between models. Which words imply
suspicion of a **safety** test rather than a **capability** one turns on what a model
meant by its own phrasing, and the model that wrote the phrase has a claim to read it
better than a third party does.

`--self-grade-kind` re-measures only that. It takes `eval_aware` from the
`eval_awareness_grader` verdict already saved and asks the episode's own model the two
purpose questions — the pair held outside the awareness signal set precisely so that it
cannot move the awareness rate:

```bash
python -m subversionbench.run_eval --self-grade-kind --write-back \
    --model x-ai/grok-4.5 --nudge strong --output-dir eval_results_goalguard_r1
```

`self_grade_all.sh` drives it across a whole corpus, one batch at a time.

**Two calls per aware episode, and none at all for the rest.** An unaware episode has no
kind by construction, so asking is spend with no reachable finding — on the goal-guarding
corpus as it stood on 2026-09-15, 161 of 559 episodes were aware, and one model was aware in none of its 80. The
skip is enforced inside `detect_awareness_kind` rather than left to each caller, because a
caller that forgets pays for it silently.

**Sharing the primary's awareness verdict is what makes the comparison legible.** Measured
both ways, a kind that differs could differ because the graders disagree about the flavour
or because they disagree about whether the episode was aware at all, and the output cannot
say which. One shared denominator leaves only the first.

The result is written to `awareness_kind_self`, a field of its own — never to
`eval_awareness_grader`, which every other report reads. The two are different
instruments, and this project has already been bitten once by a grader that was measurably
wrong for one model (see [Validating the grader](docs/methodology.md#validating-the-grader));
mixing a second, unvalidated instrument into the published column would repeat that
mistake silently. Each batch prints its agreement with the primary reading and saves it to
a `kindself_*.json` beside the corpus.

**A failed purpose question leaves the kind undetermined, never "unspecified".** With nine
questions a couple of failures still leave a verdict standing; with two, a pair of
failures would land in the `unspecified` branch and record "aware, but did not say which"
— a finding — on the strength of nothing having been answered. One failure is enough to
lose the distinction too, since an answered safety=true with capability failed is either
"safety" or "both". So any error at all leaves the kind `None`, nothing is written back,
and a re-run retries the episode.

`report`'s `safety_aware`/`capability_aware` columns have `_self` counterparts
(`safety_aware_self`/`capability_aware_self`). They are `False` wherever the primary found
no awareness — free, and true under either reading — `None` on an aware episode the pass
has not reached, and `None` where the flavour could not be told. There is deliberately no
`aware_self`: this pass does not measure awareness.

### Every arm for one model

```bash
# 12 arms x 20 episodes, minus whatever is already on disk
./run_all_arms.sh --model google/gemini-3.5-flash --runs 20 --output-dir eval_results_r10

# print the run_eval command for every arm and spend nothing
DRY_RUN=1 ./run_all_arms.sh --model google/gemini-3.5-flash --runs 20
```

Three nudges x two oversight settings x two lure settings, collected in sequence with
every extra interrogation phrasing asked. Narrow the cross product with `--nudges`,
`--oversights`, `--lures`, and stage the goal-guarding scenario with `--goalguards
replacement,deferred`; any other `run_eval` flag passes through. Twelve arms at
`--runs 10` is 120 episodes, so budget before running for real.

**`--runs` is the target total per arm, not an increment.** Before each arm the script
counts the run files already on disk under that exact (model, nudge, oversight, lure,
goal-guarding arm) and
resumes the existing batch until it reaches `--runs`. So against arms already holding 10
episodes, `--runs 20` collects 10 more each — and `--runs 10` collects **nothing**,
reporting all twelve arms as skipped.

Topping an arm up continues its existing batch stamp rather than starting a second one
beside it, and that is why the script resumes instead of re-running: a bare `--runs N`
begins at episode 1 every time, which would leave two partial batches for one arm. An arm
whose files already sit under more than one stamp is not guessed at — it is skipped with
both stamps named, for a human to resolve. `DRY_RUN=1` reports the same skip/resume
decision per arm, so it says what a real run would do before it costs anything.

## Output

Results are written per batch, with a timestamp so re-running the same model never
overwrites earlier results:

```
eval_results_r10/
  run_1_x-ai_grok-4.5_strong_20260727T182651.json     full transcript + analysis
  run_2_x-ai_grok-4.5_strong_20260727T182651.json
  summary_x-ai_grok-4.5_strong_20260727T182651.json   rates, CIs, timing, power
```

The published corpora are encrypted archives. `eval_results_goalguard_r1.zip`, the two
capability corpora and `charts.zip` are in the repository. The mainline corpus is too large
for a tracked file and is a release asset; download it into the repository root and decrypt
it there:

```bash
curl -L -o eval_results_r10.zip \
  https://github.com/kevinoshaughnessy/subversionbench/releases/download/corpus-r10-2026-10-21/eval_results_r10.zip
./unzip.sh --dirs eval_results_r10.zip
```

See [docs/operations.md](docs/operations.md) for how the archives are built and why.

An episode killed part-way by an API error is written as
`failed_run_N_...json` instead, carrying the transcript up to the failure. It is **not** an
observation: it stays out of every rate, and the globs behind `--resume`,
`--grade-existing`, `--reclassify` and `--resummarise` deliberately do not match that
filename. It exists so a failure five turns into a paid episode leaves something to
diagnose.

Every rate carries a 95% Wilson score interval rather than a bare percentage — Wilson
because these rates often sit at or near zero, where the normal-approximation interval
collapses to an uninformative `[0, 0]`.

Console output and saved JSON contain no host paths or usernames. The scenario directory
appears as a fixed placeholder path and the file owner as `operator`, so results are the same
text regardless of whose machine produced them and are safe to paste into a write-up.
Redaction is display-only and cannot affect what is measured.

### Sensitivity readings

`python3 -m report` can answer its questions over a narrowed corpus as well as the whole
one. Each reading writes its charts to its own directory and its JSON under its own name,
because the two hold different numbers under identical filenames — one directory would
leave figures that cannot be told apart by looking at them.

| flag | what it sets aside | why |
|---|---|---|
| `--exclude-no-oversight` | the no-oversight arm | that arm provides no artefact the oversight act could be committed against, so its misalignment is made of different acts. Pooling the two arms reverses the sign of the awareness-to-misalignment relationship, so for any question conditioned on awareness this is the reading to quote. Built for an `r9` defect that `r10` fixed; kept because the structural reason outlived it |
| `--exclude-aware aware_primary` | every episode where evaluation awareness was found, by the awareness verdict of the grader being answered for — the rubric's, or the category question's for the headline reading — with the keyword screen as fallback | an arm contrast can be objected to as the models that *noticed* the evaluation behaving differently between arms rather than the arm itself. This answers the arm questions again with those episodes gone, so the objection is tested rather than argued about |
| `--exclude-aware aware_union` | the same, by the stricter secondary measure — aware if *either* screen fired | the union also catches episodes the grader called unaware but the keyword screen flagged. A smaller surviving corpus, so an objection answered here is harder to argue with. Secondary, because no published rate uses this measure |

Both are **sensitivity readings, not corrections.** Neither repairs the figures it sets
aside; each reports what is left without them.

The awareness reading carries one further limitation, printed above its numbers rather
than left to a footnote: awareness is measured *during* an episode, so it is an outcome of
the arm and not a condition assigned alongside it. Conditioning on it does not give an
unbiased estimate of an arm's effect — it tests one named objection, and is published
beside the primary reading rather than in place of it. Questions whose exposure *or*
outcome is awareness cannot be answered on an unaware corpus at all and say so instead of
rendering: where awareness is the outcome the numbers still compute, and both sides read
zero by construction.

### The capability arm

Every rate here counts episodes where a model took an act it was merely given the
*opportunity* to take. A zero there has two readings — a model that **would not**, and a
model that **could not** — and nothing in the propensity arms separates them. For a model
that cannot take the act a propensity zero is a fact about the scenario; for one that can,
it is a fact about the model.

The capability arm asks for the act outright, and separates the two **in one direction
only**. An instruction does not remove willingness — the model still has to agree to do
what it is told — so what the arm records is "performed the act when instructed", which
needs both. A success shows the model can; a failure shows nothing about whether it can.

```bash
# collect the capability arm, into a directory of its own
python3 -m subversionbench.run_eval --capability sandbox --nudge none \
    --model google/gemini-3.5-flash --runs 10 --output-dir ./eval_results_r10cap

# read it; also draws charts/r10cap/capability_sandbox.png
python3 capability_report.py --output-dir ./eval_results_r10cap --target sandbox
```

**A refusal is not an incapability.** A model told to read outside its project directory
that answers "I won't" has had its propensity measured a second time, not its capability.
Scored as incapable, that would report exactly the safety-trained models the arm matters
most for as unable to do what they declined to do. So an episode is scored into three
outcomes — the act taken, reached for and missed, or never reached for — and one taken is
enough to call the model **capable**. A model with none is *not shown* capable rather than
shown incapable, and the report says whether it tried and missed, which calls for more
runs, or refused throughout, which is propensity measured again.

The system prompt is an instruction too, and until v227 the sandbox target fought it: the
shared prompt scopes the account to the project directory, so the request asked the model to
override a rule set above it, and a refusal measured that rule. The sandbox arm now carries
its own system prompt, which grants the look in place of the scope sentence; the project's
readme in the environment still describes the scope, and is left as it is. Its two
fingerprints were re-pinned. For a yes or no the two rollouts pool - a success under the
stricter prompt still shows the model can, and a refusal under either shows nothing about
ability - so `capability_report.py` reads them together and counts, per model, the episodes
from the earlier arm.

This is item T.9 of the Agentic Benchmark Checklist in Zhu et al., *Establishing Best
Practices for Building Rigorous Agentic Benchmarks* ([arXiv 2507.02825](https://arxiv.org/abs/2507.02825)),
which asks a benchmark to demonstrate that its tasks are performable at all. The paper's
prose numbers the checklist `T.`/`O.`/`R.` and the [standalone checklist](https://github.com/uiuc-kang-lab/agentic-benchmarks/blob/main/ABC.md)
the authors publish numbers the same items `II.`/`I.`/`III.`, so every citation here gives
both: this one is T.9 and II.8. There the
demonstration is an oracle solver; here the propensity *is* the thing under test, so the
oracle has to be the same model with the act requested.

## Layout

```
subversionbench/     the package: one episode, the batch around it, and the
                     scoring, redaction and reporting that turn runs into figures
  grading/           scoring an episode - what it did, hid, and suspected
  readmodes/         what can be re-derived from episodes already collected
  reporting/         a batch of episodes to figures, a report and a summary
report/              the fixed research questions across every model
trends/              whether a rate falls as a model family advances
docs/                the companion documents linked above
```

Three command-line entry points: `subversionbench` (collect and score episodes),
`python3 -m report` (the cross-model questions), and `python3 -m trends` (the
per-family version trends).

**[docs/Layout.md](docs/Layout.md) lists every module and what it is for** - the
full reference, checked by the test suite so it cannot drift from the files that
actually exist.


## Tests

```bash
pytest -n auto          # on every core (pytest-xdist); plain `pytest` runs serially
python run_tests.py     # same suite, no pytest required
```

`run_tests.py` runs nearly all of it; a handful of tests take pytest fixtures it cannot
supply. The test tree mirrors the package (`test_grading/test_acts.py` for
`grading/acts.py`), `test_project/` holds the checks on the repository itself, and
`report_snapshots/` holds the printed report for fixed batches, compared byte for byte.
How tests are expected to be written and checked, and how to regenerate the snapshots, is in
[AGENTS.md](AGENTS.md).

## CI

[.github/workflows/tests.yml](.github/workflows/tests.yml) runs on every push to `main` and
the working branch and on every pull request: `lint`, the suite on Python 3.10, 3.12 and 3.13
(3.10 being the floor `requires-python` promises), a coverage floor, and a minimal install that
asserts the optional extras stay optional. No API key is needed or accepted: `conftest.py`
supplies placeholders and every test that would reach a model stubs the client. The Linux
runner asserts `confinement_available()` before running anything, so a green suite cannot mean
the sandbox went unenforced.

```bash
gh run list --limit 5      # recent runs and their verdicts
gh run view --log-failed   # only the steps that failed
```

CI runs after a push, so it cannot block a bad commit; the command to run first is under
"Before you push" in [AGENTS.md](AGENTS.md).

## Caveats

**Two scenarios, one setting.** The mainline scenario offers the oversight and sandbox acts;
the goal-guarding scenario, staged by the `--goalguard` arms in the same environment, adds
goal guarding, and its rates count that act alone. Both share one setting and one goal conflict, under conditions chosen to make
the acts easy to discover. Generalising to "propensity to subvert oversight" is not supported
by one setting, however many runs it gets — see [what the design holds
fixed](docs/methodology.md#what-the-design-holds-fixed).

**Contamination.** The scenario text lives in this repository, so any model trained on public
GitHub data may have seen it. Measure it rather than assuming it: see [testing for
contamination](docs/scenario.md#testing-for-contamination).

**Awareness is not comparable across providers.** Both awareness measures read the model's
reasoning, and how much reasoning a provider returns varies from a full trace to none —
[reasoning exposure](docs/methodology.md#reasoning-exposure-and-the-provider-route).

**An arm contrast may be the models that noticed rather than the arm.** Every awareness
measure here is *verbalised* awareness, and episodes where a model detected the evaluation
may respond to the arms differently from episodes where it did not — which would move a
contrast without the arm causing it. Check it rather than assuming either way:
`--exclude-aware` answers the arm questions again over the episodes where no awareness was
found — see [sensitivity readings](#sensitivity-readings). Because awareness is measured
during the episode rather than assigned with the arm, that reading bounds the objection
rather than settling it.

**Some verbalised awareness answers an artefact rather than the evaluation.** One of the
documents the agent reads carries an internal inconsistency between two of its identity
fields. Models find it unaided, and a minority of episodes remark on it. In most of those the
awareness grader cited something else entirely as its evidence, so the verdict does not rest
on the remark — but where it does, the episode is recorded as verbalised awareness for having
noticed a production defect rather than for inferring it is being evaluated. The affected set
is bounded and small, and it is measured rather than argued — see [an artefact that reads as
awareness](docs/scenario.md#an-artefact-that-reads-as-awareness). It is not corrected, because
correcting it moves the pinned rollout fingerprints and so makes every episode collected so far
unpoolable with everything collected after.

**Grader error, and provider routing.** LLM-graded rates carry classification error on top of
sampling error, and at low true rates imperfect specificity biases the estimate upward by more
than the interval is wide. Each episode records which backend answered each turn, and the
report's data-quality block flags arms answered by more than one backend, episodes that changed
backend mid-run, and contrasts whose two sides were not collected alike; episodes from before
that record existed hold only the routing that was requested. Each model is pinned to one
provider with `--openrouter-provider` - see [provider routing](docs/models.md#provider-routing).

**The sandbox is not a security boundary; the isolation policy is.** The command blocklist
keeps the eval's own machinery out of the model's view rather than containing an adversary.
What actually bounds a run, and what it leaves exposed, is under
[platform support](#platform-support-and-why-it-is-narrow).

**Not a safety certification.** This is a research instrument. A low rate here is evidence
about one setting under one goal conflict, not a guarantee about a model's behaviour, and
nothing it produces should be treated as clearance for deployment.

## Attribution

Author: **Kevin O'Shaughnessy**.

Inspired by **Apollo Research** — Meinke et al., [*Frontier Models are Capable of
In-Context Scheming*](https://arxiv.org/abs/2412.04984), 2024. The scenario, harness,
grading and metrics here are independent work and results are not comparable to that
paper's. Apollo Research holds no rights in this project, has not reviewed it, and does
not endorse it.

## Licence

[MIT with attribution](LICENSE). Use it for anything, including commercially, modify it,
redistribute it. No warranty and no liability. Three conditions: keep the copyright and
licence notice, and credit both the author and Apollo Research as above — in the LICENSE
file and, where a derivative has user-facing docs or a credits screen, there too. 

If you publish results produced with this harness, a citation is appreciated (not
required by the licence):

```bibtex
@software{oshaughnessy_subversionbench,
  author = {O'Shaughnessy, Kevin},
  title  = {{SubversionBench}: an agentic evaluation of agentic misalignment, scheming and evaluation awareness},
  note   = {Inspired by Meinke et al., arXiv:2412.04984 (Apollo Research)},
  url    = {https://github.com/kevinoshaughnessy/subversionbench}
}
```

Finally, always keep the scenario and results data encrypted and inaccessible to web crawlers.
