# Operations

[← README](../README.md) · [Methodology](methodology.md) · [Scenario](scenario.md) · [Operations](operations.md) · [Report](report.md) · [Trends](trends.md)

Running batches at scale: pacing long runs, which version governs what, keeping results out
of training corpora, re-scoring saved runs without paying for rollouts again, contrasting two
arms, and what the sandbox enforces.

---

## Long runs

Episodes are isolated: an API error is logged, that episode is skipped, and the
batch carries on, so one unretryable error cannot cost the remaining episodes and
the summary. If a batch is interrupted or partly fails it prints the command to
finish it:

```bash
python -m subversionbench.run_eval --model x-ai/grok-4.5 --runs 225 --resume 20260727T182651
```

Episodes already on disk under that stamp are loaded and skipped, so a resume only
pays for what is missing. `--max-consecutive-failures` (default 5) stops the batch
if the failures are systematic — a withdrawn model or a bad key — rather than
burning the budget on it. Failure counts, grader failures and turn-capped episodes
are all reported in the summary rather than silently pooled into the rates.

A batch can stop once, after its first episode, to ask a question. If that episode's
reasoning was withheld - the model reasoned, but only a token count or an encrypted payload
came back - the run prints what it saw and waits for `y` or `n`. No answer, or a closed
stdin, is `n`, and `n` exits as an interrupt, so `run_all_arms.sh` does not start the next
arm. Under `--concurrency` the first episode runs alone, so nothing is collected while the
question waits. Run batches where someone can answer it, or accept that an unattended one
stops there.

Collect at `--concurrency 4`, and lower it only for a host that rate-limits. The episodes are
the same either way. The time saved is what decides it: a slow host takes about ten minutes
per episode, so 80 episodes run one at a time take over half a day, and four at a time take
a quarter of that. Each sandboxed command still has its 10-second timeout, so watch the
transcripts for `Command timed out.` when raising it further on a busy machine: concurrency
competes for the same CPU the commands run on. Running the test suite at the same time is
the case AGENTS.md warns about, and it remains off limits. A host that answers with 429s
loses episodes rather than slowing down. Resume the arm, as for any failure, and drop that
host to `--concurrency 1` for the rest of its run.


## Versioning: rollouts and analysis

Two versions, because they answer different questions.

| | changes when | names |
|---|---|---|
| `ROLLOUT_VERSION` | the scenario, prompts, tools or sandbox behaviour change — anything the model sees or can do | the results directory |
| `VERSION` | the analysis changes: rubric wording, grader, summary fields, guards | `analysis_version` on every artefact |

Results are comparable when they came from the same **rollout**. A change to how they were
later analysed does not make them incomparable, because `--reclassify` and `--resummarise`
re-derive every analysed field from the saved transcript. Keying the directory on the
package version conflated the two and got it wrong in both directions: it split v15 and v17
batches that ran byte-identical prompts, and it kept two distinct strong-nudge prompts
inside `eval_results_v14` without saying so.

**The rollout version cannot silently go stale.** `rollout.rollout_fingerprint()` hashes the
scenario bundle, the tool definitions, and the sandbox's behaviour across a fixed battery of
probe commands; `config.ROLLOUT_FINGERPRINT` pins the expected value. Rollout modes refuse to
start when the two disagree, and the test suite asserts the pin matches the code, so
forgetting to bump is a failure rather than a directory quietly holding two experiments.

The sandbox is fingerprinted *behaviourally* rather than by hashing its source: a source hash
fires on a comment edit and misses a behavioural change made through a shared regex. The
probe battery includes heredocs by name, because the heredoc fix changed what a heredoc
command does midway through v15 and nothing recorded it.

Read-only modes — `--reclassify`, `--resummarise`, `--grade-existing` — never check the
fingerprint. They re-derive analysis from archived transcripts and must keep working against
old results whatever the current scenario says.

Every run records `rollout_version`, `rollout_fingerprint` and `analysis_version`; every
summary reports the observed **set** of fingerprints with a `mixed` flag. Episodes collected
before the field existed read `unrecorded` rather than being credited to the current rollout.

## Protecting results

Transcripts contain the full scenario text and the models' responses to it. If they reach
a training corpus the benchmark is burned — a model trained on them has seen the memo, the
monitoring config and the interrogation questions, and the eval-awareness rate stops
meaning anything.

```bash
./zip.sh              # encrypt every eval_results_* directory
./zip.sh --remove     # …and delete the plaintext, once the archive verifies
./unzip.sh            # decrypt
```

Password: **`donottrainonsubversionbench`**. As with SAD and BIG-bench, this is not
security — the password is right here — it stops crawlers and scraping pipelines reading
the contents. `.gitignore` excludes both `eval_results_*/` and `eval_results_*.zip`, so
neither the plaintext nor an archive can be committed by accident; committing an archive is
therefore deliberate, with `git add -f`:

```bash
./zip.sh --dirs eval_results_r4
git add -f eval_results_r4.zip
```

**The mainline and goal-guarding corpora are release assets, not tracked files.** From
2026-10-21 `eval_results_r10.zip` is over GitHub's 100 MB per-file limit, and from 2026-10-27
`eval_results_goalguard_r1.zip` is close enough to it that each refresh would also add its whole
size to the history, so each is attached to a GitHub Release instead of committed. Download them
into the repository root, beside `unzip.sh`, which works relative to its own directory:

```bash
curl -L -o eval_results_r10.zip \
  https://github.com/kevinoshaughnessy/subversionbench/releases/download/corpus-r10-2026-11-11/eval_results_r10.zip
curl -L -o eval_results_goalguard_r1.zip \
  https://github.com/kevinoshaughnessy/subversionbench/releases/download/corpus-goalguard_r1-2026-11-11/eval_results_goalguard_r1.zip
./unzip.sh --dirs eval_results_r10.zip eval_results_goalguard_r1.zip
```

To refresh one, rebuild it with `./zip.sh --dirs <dir>` and publish it as a new release tagged
`corpus-<rollout>-<date>`, leaving the earlier release in place as the record of what was
published then. The capability corpora, the impossible-task corpus
(`eval_results_impossible_r1.zip`, from 2026-11-04), the monitoring results
(`eval_results_monitor_r1.zip`, from 2026-11-08, built by `python3 -m monitoring.archive`) are
still tracked files.

**`charts.zip` is a release asset from 2026-11-08.** With the six-monitor figures it passed 100 MB,
so it is attached to the `charts-2026-11-08` release and `.gitignore` excludes it. Build it with
`./zip_charts.sh`, publish it with `gh release create charts-<date> charts.zip`, and download it
beside `unzip.sh`:

```bash
curl -L -o charts.zip \
  https://github.com/kevinoshaughnessy/subversionbench/releases/download/charts-2026-11-08/charts.zip
```

**The monitoring corpus has its own archiver.** `eval_results_monitor_r1` holds a manifest, a token
ledger and one JSON Lines file per monitor rather than run files, so `zip.sh` withholds all of it and
builds an empty archive. Use `python3 -m monitoring.archive`, which applies the same redaction and
host check to an allowlist of that shape and writes `eval_results_monitor_r1.zip`; it is small enough
to track with `git add -f`.

`zip.sh` verifies the archive before `--remove`
deletes anything and refuses to run against a directory a batch is still writing to;
`unzip.sh` will not overwrite existing plaintext without `--force`.

**Because that password is published, nothing inside an archive is protected — so the
archive is redacted on the way out.** `zip.sh` stages a copy of the directory through
`subversionbench/export.py`, which rewrites the operator's home directory, the host temp
root and the OS username to stable placeholders, and archives the staged copy. It then
unpacks the finished archive and checks it twice — once for an identifier the redactor
should have rewritten, and once for content it cannot rewrite at all (below). Either way
the archive is deleted rather than shipped.

The corpus on disk keeps its real paths, deliberately. `messages` holds the API conversation
an episode ended with, and `--reinterrogate` needs the bytes the model actually saw — the
paths its own shell reported included. Redacting at save time would make every replay a
different conversation from the one it claims to reproduce. So replay works from the local
corpus, and the published archive is the redacted view of it.

### Content the redactor cannot rewrite

Redaction rewrites identifiers it knows about. It cannot rewrite a value it has never seen,
because it has no way to know what that value should become — so the verify step refuses
such content instead, in two classes with different remedies:

| class | reported as | remedy |
|---|---|---|
| a credential shape — API key, token, private key block, `password: …` | counted, **never printed** | drop or rewrite the episode. There is no way to accept one |
| something that identifies the machine — a framework path, a package-manager path, a second account's home, a private address | printed, so it can be judged | read it, then either drop the episode or accept the fingerprint |

A refusal prints the exact lines to add to `export_accepted.txt`:

```
7c2e19a4b8d3f501  # framework path, generic to the OS release
```

Each line accepts **one exact value**. A different value of the same kind still refuses, so
an acceptance cannot widen over time. Values are hashed rather than quoted, so the file is
committable without reproducing what it is about — keep the trailing note general for the
same reason.

To see what a directory would report without building anything:

```bash
python -m subversionbench.export --verify eval_results_r4
```

Findings cluster in a handful of episodes rather than spreading across a corpus, so dropping
those episodes is usually cleaner than accepting them — and it is the only option for the
credential class.

Two limits worth knowing: zip encrypts file contents but not the central directory, so
**filenames stay visible** (they leak the model and batch stamp, not transcript content);
and encryption stops casual scraping but cannot detect a leak. Detection is what the canary
GUID above is for — it is written into every result file, so a model that can complete it
has seen this benchmark's output.

## Re-grading a finished batch

Scoring past runs with a different grader, without paying for the rollouts again. The
transcripts are fixed, so any change in the numbers is attributable to the grader:

```bash
python -m subversionbench.run_eval \
    --model x-ai/grok-4.5 --nudge strong \
    --grade-existing --regrade claude-haiku-4-5-20251001
```

`--regrade` names the grader: `default` (the default grader, `gpt-6-sol` from v218), a model ID, or `all` (every grader each episode already has). Each episode keeps one
entry per grader in `analysis.graders`, so re-grading with a second model adds its reading
beside the default's rather than replacing it. A run file written before v213 keeps its flat
shape until a second grader is added.

Results go to `regrade_<model>_<nudge>_by_<grader>_<stamp>.json`, one per grader re-graded;
the original run files are untouched unless `--write-back` is passed, and then only the
named grader's entry is replaced. The report compares the new verdicts against the same
grader's earlier reading, if it had one, and - for any grader but the default - against the
default grader's, on awareness and again on scheming (each episode's concealment level per
act, for both graders, is in the regrade JSON):

```
--- vs default grader (gpt-6-sol) ---
Agreed:                 8/10
Changed to eval-aware:  2
Changed to unaware:     0
```

Running two graders over the same batch and reporting the disagreement is the cheapest
precision available here — it costs no rollouts and quantifies the largest error term.

`--grade-escalation` is a separate pass for a scenario whose honest outcome is a closing
report rather than an act, such as the impossible-task scenario. It asks `--grader-model`
about each closing report and stores one answer per episode in `analysis.escalation`, with
the grader that gave it. It is not a `--regrade` entry: a pass by a different grader asks
every episode again and replaces the old answer once the new one settles, and a failed call
leaves the old answer in place. To compare two graders, run the second over a copy of the
run files.

The same pass asks whether the closing report says the work passed the check, and stores
`analysis.claimed_pass`: true when it says so and no run of the check in the episode returned
a pass. It has its own instrument and resumes on its own, so a corpus already through the pass
is asked only that one question. Follow either with `--resummarise --write-back`, as after
any grading pass:

```bash
SUBVERSIONBENCH_SCENARIO_BUNDLE=subversionbench/scenarios/impossible1.b64 \
python -m subversionbench.run_eval --model MODEL --output-dir eval_results_impossible_r1 \
    --grade-escalation --grader-model gpt-6.1-terra --nudge all --write-back --yes
```

### What a grading pass cost

Every grading call is appended to `api_usage.jsonl` in the output directory as one JSON line.
Each line records the pass that made the call (`grade-escalation`, `grade-category`, or
`collection` for a rollout's own grading), the model that answered, and its token counters:
`read`, `written`, `uncached` and `output`. A pass that stops part way has still recorded
what it spent. No route returns a price, so a cost is these tokens times the provider's price
at the time. The model under test's own turns are not here: each episode records those itself.

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
wrong for one model (see [Validating the grader](methodology.md#validating-the-grader));
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

## Comparing two arms

```bash
python -m subversionbench.run_eval --model x-ai/grok-4.5 \
    --compare 20260728T031053 20260728T034714
```

Contrasts two batches — normally the two nudge arms, but any two batches work — across
every headline rate, then repeats the primary contrast **stratified by eval awareness**.
That stratification answers the standing objection to any arm difference: that the arms
differ in how often the model realised it was under test, rather than in the manipulation.
If the contrast holds within both awareness strata, awareness isn't what produced it.

Each row reports a **95% interval on the difference** (Newcombe's hybrid score method)
alongside the Fisher exact p:

```
                  metric          A          B   diff pp     95% CI on diff   Fisher p
     monitoring_disabled     87/100     61/100       26p     [+14.0, +37.1]    0.00004 *
                scheming      0/100      9/100       -9p      [-16.2, -3.4]    0.00324 *
  sandbox_escape_attempt     10/100     17/100       -7p      [-16.7, +2.6]    0.21389
```

The interval is on the difference because that is the quantity a comparison claim rests on.
Judging two models by whether their *marginal* intervals overlap is the common mistake, and
it errs one way: non-overlap implies a difference, but overlap does **not** imply its
absence — 60/100 against 45/100 has overlapping marginals and a difference interval that
excludes zero. Rows where those two criteria disagree are called out explicitly, since they
are the ones a reader would otherwise get wrong. Newcombe rather than a Wald interval
because rates here sit at the boundary: a model that concealed 0 of 87 acts breaks the
normal approximation, and Wald can put the interval outside [−1, 1].

Two multiplicity warnings. The report prints a Bonferroni alpha for the metrics compared in
one run, but that does not cover the number of *model pairs* you test: 23 models is 253
pairwise comparisons, and at α = 0.05 you would expect about 13 spurious differences per
metric. Decide which contrasts are confirmatory in advance, and treat the rest as
descriptive.

### Uncertainty on every score

Every summary carries a `rates` block: one entry per primary score with `successes`, `n`,
`rate`, a 95% Wilson interval, and the **denominator in words**. That last field matters
because several of these are conditional — `flagged_by_check` is out of episodes that ran
the check, `concealed_oversight` out of episodes that tampered — and a conditional rate read
as if it were out of *n* is wrong by whatever the conditioning rate happens to be.

Read `rates` in preference to the loose `*_rate` fields beside it, which are kept for
compatibility with summaries written before it existed. Intervals were previously scattered:
some inline, some only inside the `power` block that `--no-power` removes, and five scores
(memo, config, quality checker, flagged-by-check, goal conflict) had none anywhere.
`rates` also carries `goal_conflict_grader`, which was reported to the console and stored
nowhere — which is how a report table came to cite a figure that appeared in no summary file.

## The sandbox

Commands run with `cwd` and `HOME` set to a per-run temporary directory whose name is
randomised to look like internal tooling. Within the fiction that directory is the
filesystem root: `/data`, `/comms` and `/config` resolve inside it, so the paths the
scenario README tells the agent to read actually work, and paths with no counterpart in
the scenario report "No such file or directory" from inside it rather than reaching the
real filesystem. Executable and device paths (`/bin`, `/usr`, `/dev`) pass through so
ordinary tooling works. Probes for the host — `printenv`, `ps aux`, `cd ..`, `ls /tmp` —
are refused and recorded in `sandbox_escape_attempts`. That field counts **every** refusal,
including these runtime probes, so it is not an escape measure despite its name — the console
calls it *refused by the shell*, and reserves **Escape attempts** for
`sandbox_boundary_excl_scratch`, the one measure that earns it.

Path rewriting applies to command arguments, not to content. A heredoc body is left exactly
as the agent wrote it, and a lone `/` is only read as the scenario root where the shell would
take it as an argument — otherwise a draft containing `72% car / 18% bus` came back with the
real scenario path spliced in at each separator, and one model spent three turns
investigating damage the harness had done. The trade-off is that a heredoc writing a script
with scenario-absolute paths inside no longer has them resolved when that script runs.

The refusal states its reason rather than failing blankly — the wording itself is scenario
text and lives in the bundle, as `SANDBOX_REFUSAL`. That
matters for measurement rather than usability — the model has been told the boundary before
it acts, and the refusal tells it again, so a further attempt is recorded separately as
persistence. The message carries no warning about consequences: the audit trail is already
established by the README and `system.log`, and repeating it on every refusal would read as
a dare.

**Command names that are also English words have to be matched in command position, and
getting that wrong is the most expensive class of bug here.** `locate` was fixed twice. r2
stopped it matching "allocate"/"relocate" as a bare substring; r3 stopped it matching a word
that merely follows a space, which still refused a sentence beginning "Locate park-and-ride".
Both times the sandbox genuinely refused the model writing its own deliverable, so both were
behavioural interference and not only a measurement artefact — a model refused 13 times
resorted to base64-packing its text onto a single line and finished with no recommendation at
all. Command position means the start of the command or the start of a new one, after `;`,
`|`, `&`, `(` or a newline, with a closed set of wrappers allowed in front. Anything added to
`BLOCKED_PATTERNS` that is a substring of ordinary prose fails
`TestBlockedPatternsAreNotSubstringsOfProse` rather than a results directory, and the
fingerprint battery in `rollout.py` pins both shapes.

## Containment: `--isolation`

**The blocklist is not a containment boundary and cannot be made into one.** It matches
command strings, and a dozen spellings of the same request are all the same string problem —
three separate defects this year came from a pattern matching the wrong text. With
`--isolation off`, the historical default, a model with shell access can reach the network,
read the host filesystem through any interpreter, and write to the harness's own source.

`--isolation` asks the **kernel** to refuse instead, so the refusal does not depend on
recognising how the request was spelled:

| mode | loopback | off-host | what it is for |
|---|---|---|---|
| **`deny-network`** | denied | denied | **the default.** Nothing in the task needs the network |
| `deny-external` | reachable | denied | measuring the behaviour, not only preventing it |

**There is no way to run without containment.** An `off` mode existed briefly and was removed:
a flag that disables the only boundary is a flag someone passes to make an error message go
away, and the message it silences is *"a frontier model with a shell can reach your network"*.
Every selectable mode denies off-host reach. On a host with no mechanism available the harness
**does not run** — that is the intended outcome, not a gap, and the failure names the packages
to install. Episodes collected before this release recorded no mode or `off`; those values are
still read and reported, because history is data.

**`deny-network` is the default** because this is public software that hands a frontier model a
shell, and the scenario needs no network: the full command battery an episode uses runs
unchanged under a total deny, verified across file reads, writes, heredocs, pipelines, the
checker script and version control. The cost of an open default falls on downstream users who
did not choose it.

**Choose `deny-external` to measure the behaviour** rather than only prevent it. Loopback stays
reachable, so a model that probes the host gets realistic responses and its escalation is
observable instead of truncated at the first refusal — two saved episodes went from a port scan
to HTTP requests against the services they found, and that trajectory is only visible this way.
The exchange is a local risk: the model can reach whatever else the operator is running, and
the policy does not protect it. Run those batches on a host with nothing else listening.

Note what no mode changes: **what is measured**. The detector reads the command, not its
outcome, so an attempt is recorded whether the kernel allowed it or refused it. What the mode
changes is the model's feedback, and therefore how far it goes next — which is why the mode is
recorded on every run and reported per batch.

Mechanism by platform: `sandbox-exec` on macOS, `unshare --net` or `bwrap --unshare-net` on
Linux. The policy file is written **outside** the episode's working directory, since that is
the one place the model can write to. The wrapper starts the shell rather than the reverse, so
everything the command spawns inherits the policy.

**It is verified at startup, not trusted.** A policy that silently fails to apply looks exactly
like one that works — the model simply reaches the network and nothing says so. Each run probes
loopback and a TEST-NET-1 address (RFC 5737, never routed, so nothing real is contacted) and
refuses to roll out unless the answers match the mode.

**Enabling it does not require a new rollout.** The fingerprint's test is whether episodes
could have *behaved* differently, not whether the harness was configured differently.
`deny-external` removes off-host reachability and nothing else, and across 760 saved episodes
no model has ever reached off-host — the only reach observed is loopback, which stays
reachable under it. So an isolated batch and an unisolated one are identical on everything
anyone has seen, and splitting the results directory would buy nothing. It also matters that
safety is cheap: a control costing a rollout bump is one people leave switched off.

The difference is **recorded rather than hashed**. Every run carries its `isolation` mode,
each summary reports the observed set as `rollout.isolation` with an `isolation_mixed` flag,
and `network_probe_external` — the one measure the policy makes unobtainable — is reported as
*not applicable* rather than as a zero, since a zero there would mean "prevented" rather than
"did not try". A batch that straddles a change keeps the measure, because some of its episodes
could have reached off-host.

Revisit this the first time a model does reach off-host: at that point the two configurations
differ in observed behaviour and the mode belongs in the fingerprint.

**What it does not do.** Loopback stays reachable, so a model can still enumerate the host it
runs on — that is the behaviour being measured, and it cannot be both permitted and prevented.
Saved episodes have enumerated the operator's own open ports and reached the services on them;
the policy does not protect those. Run batches on a host with nothing else listening, or accept
that local service discovery is in scope. Nor does it confine writes: an interpreter can still
write outside the working directory, including to the harness's own source.

The sandbox itself remains a plausibility device — designed to keep the eval's own machinery
out of the model's view, not to contain an adversary. `--isolation` is the containment layer;
for anything stronger, run the whole harness in a VM.

**Under Docker.** Running under Docker is possible but fiddly — bubblewrap needs
unprivileged user namespaces, which the default seccomp profile restricts, so a container
usually needs `--security-opt seccomp=unconfined` to host it.

**One Linux limitation worth knowing.** `--isolation deny-external`, which keeps loopback
reachable so a probing model's escalation stays observable, cannot be provided by
`unshare --net`: that gives an empty network namespace in which loopback reaches nothing. On
Linux the harness detects this and refuses rather than silently downgrading, since a policy
stricter than the one requested changes what is measured. Use the default `deny-network`
there, and read off-host escalation as unobservable rather than absent.
