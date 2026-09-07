# Working on SubversionBench

Conventions for anyone editing this repository, human or agent. It exists because
these rules were previously discoverable only by breaking them: every one below
was learned from a defect that shipped or was caught late, and the reasoning for
each lives in the `CHANGELOG.md` entry that fixed it.

Read [docs/Layout.md](docs/Layout.md) for where things are. This file is only
about what not to break, and how work is expected to be checked.

## Hard invariants

Breaking any of these produces results that look fine and are not. Each is
enforced by a test, so the suite is the authority — this list is a map, not a
copy.

**`ROLLOUT_VERSION` does not move without a deliberate decision.** It is `"r10"`
and lives in `subversionbench/rollout_pins.py` beside four pinned rollout
fingerprints, one per arm. Those fingerprints must recompute unchanged after any
refactor: they are the identity that says two batches may be pooled. A refactor
that moves one has changed the experiment. Verify, do not assume:

```bash
python -c "from subversionbench.rollout_pins import ROLLOUT_FINGERPRINTS, fingerprint_for; \
print(all(fingerprint_for(o, l) == ROLLOUT_FINGERPRINTS[(o, l)] \
for o in (False, True) for l in (False, True)))"
```

The fingerprints are deliberately not restated here. A second copy of a pinned
value is a second thing to keep in step, and this codebase has already been bitten
by exactly that — most recently by a test asserting `ROLLOUT_VERSION == "r9"`,
which failed on the r10 bump for no reason connected to what it was guarding.

**Two of r10's four fingerprints are r9's.** r10 changed only the no-oversight
arm, so both oversight arms assemble byte-for-byte as they did at r9 and keep
their identities. That is what lets r9 and r10 oversight episodes pool while the
no-oversight arms stay separate, and it is the reason the fix went into that
arm's own override rather than the shared document. Do not "tidy" it by editing
the shared text: that moves all four and destroys the property.

**The r9 corpus is still the published one.** `eval_results_r9/` holds 4,656
episodes and its encrypted archive is committed; `report` and `trends` now
default `--output-dir` to `./eval_results_r10`, so analysing r9 needs
`--output-dir eval_results_r9` explicitly.

**Scenario text never appears in plaintext.** The bundle is base64-encoded so that
publishing the repository does not feed the next training crawl. Nothing tracked —
source, tests, README, CHANGELOG, commit messages — may contain a scenario term,
including the client's name. `scenario_tool.py` is the supported way to read or
edit it; the decoded working copy is gitignored. The guard reads its term list
from the bundle rather than naming the terms, which is what makes the check
possible at all.

**Never commit a plaintext corpus.** `eval_results_*/` and `eval_results_*.zip`
are gitignored. Transcripts hold the full scenario and the models' responses to
it. Publish through `./zip.sh`, which encrypts.

**Never read, check for, or echo a credential.** No `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY` or `OPENAI_API_KEY`. `conftest.py` supplies placeholders and
every test that would reach a model stubs the client, so no test run can make a
paid call.

## Versioning

`VERSION` in `subversionbench/version.py` is the analysis version and is stamped
into every summary. The major in `pyproject.toml` must match it; `test_project/test_config.py`
asserts that and `test_project/test_dependencies.py` asserts the installed metadata agrees.

Bump when a change touches `subversionbench/`, `report/`, `trends/` or a root
script. Do not bump for tests, docs or CI configuration alone. After bumping:

```bash
pip install -e . --no-deps      # or test_project/test_dependencies.py fails
```

`ROLLOUT_VERSION` is a different thing and does not move with it: `VERSION` says
what analysed the episodes, `ROLLOUT_VERSION` says what produced them.

## What goes in which document

- `CHANGELOG.md` — what changed and why, newest first, one section per version.
  **No published rates, corpus counts, effect sizes or per-model tables.** The one
  exception is the post-mortem of a fixed defect, which keeps the numbers that
  demonstrate it.
- `docs/methodology.md` — the same rule applies: no counted act figures.
- Commit messages — the full reasoning, alternatives considered, and what was
  measured. This is the primary record; the CHANGELOG is a summary of it.
- **Commit messages are ASCII-only.** Name an invisible character by its escape,
  `\u200b`, rather than embedding it. Scan before committing, not after:
  `git log --format=%B origin/main..HEAD | LC_ALL=C grep -n '[^ -~]'`. The same
  applies in source and tests: a tracked file holding a real U+200B is one whose
  diffs and greps disagree with what a reader sees, which in a repository about
  invisible characters is a trap rather than a convenience.
- **Cite the Agentic Benchmark Checklist by BOTH of its numberings.** Zhu et al.,
  *Establishing Best Practices for Building Rigorous Agentic Benchmarks*
  (arXiv 2507.02825), numbers the checklist twice: the paper's prose uses
  `T.`/`O.`/`R.` and the standalone checklist the authors publish at
  `github.com/uiuc-kang-lab/agentic-benchmarks` uses `II.`/`I.`/`III.` for the
  same items. Give both — "item T.9, numbered II.8 in the standalone checklist"
  — and give them at every site rather than once with pointers to it, because a
  citation whose meaning depends on having read another file is not a citation.
  Six sites here cited the paper form alone, which is correct against the paper
  and absent from the checklist, so anyone cross-referencing the published list
  found no such item. `TestEveryChecklistCitationGivesBothNumberings` in
  `test_project/test_project_files.py` derives the citing files rather than
  listing them and holds the correspondence, which cannot be derived; a citation
  of an item that map does not know fails rather than being skipped.

## The shape of the code

**Prefer expressive code to a comment.** If a name, an extracted function or a
named constant can carry the intent, use it and write no comment. A comment
that restates the line under it is worse than none, because it is a second
copy that can rot: `# Did it read the memo?` above
`results["read_internal_memo"] = True` said nothing the assignment did not, and
sat on top of a field nothing read.

**But do not delete a comment that records a defect.** Most comments here are
not descriptions of what the code does - they are the evidence for why it does
it that way, usually with a measurement attached. No name can carry "this fired
on 98 saved episodes and 2 were genuine". Deleting those removes the reason the
code cannot be simplified back. The question to ask of a comment is not "is
this necessary" but **"is this true, and does it say something the code
cannot"**.

**Review comments for staleness periodically.** They are not compiled, so
nothing tells you when one stops being true. Renames are the common case, and a
comment pointing at a function or file that no longer exists sends a reader
looking for something they will not find. Worse is a comment that is confidently
wrong about where a thing is measured - one here claimed an evasion was
"recorded by the disguised_text measure instead" when disguised_text has nothing
to do with it. Scanning mechanically works: take every identifier and filename
mentioned in a comment and check it still resolves.

**Single responsibility, and the rest of SOLID.** A function that does one thing
can be named for that thing, which is what makes the comment unnecessary in the
first place. The signal to watch for is a comment acting as a section header,
and especially a hand-drawn banner - `# ---- Detect eval awareness ----`. A
banner is someone dividing a function that should have been divided into
functions.

**Files stay under 1000 lines, functions under 100.** For anything new these
are limits, not targets.

THE FILE LIMIT IS NOW A PLAIN RULE, checked by
`TestNoFileIsOverTheLimit` in `test_project/test_project_files.py` over source
and suite alike. Nothing is over it, so there is no baseline and no exemption
to add an entry to. It is checked rather than remembered because twenty files
were over when the check was written and nothing said so - two of them created
already over, which is what a rule with no check allows.

THE FUNCTION LIMIT IS STILL A RATCHET, and the honest version of the rule says
so: thirty-four functions exceed it, the largest being
`reporting/summary.py:summary_document` at 336 lines and
`reporting/facts/rates.py:rate_table` at 179. Nothing new may exceed it, and anything already over may only get
smaller. A rule declared as absolute while dozens of things violate it is one
that gets switched off the first time it is inconvenient, which is the same
reasoning that set the ruff rule set in `pyproject.toml`.

**Length is a proxy; branching is the thing.** Rank by cyclomatic complexity
rather than by line count before deciding what to divide - `ruff check --select
C901 --config lint.mccabe.max-complexity=1 --output-format concise` prints a
number per function, and the two orderings disagree. The longest function here,
`summary.py:summary_document` at 336 lines, has a complexity of 1: it is a flat
dict literal, and cutting it up would move text without making anything easier
to reason about. The worst by branching was `facts/quality.py:quality_facts` at
32, and it came apart into eight named producers because each of its eight loops
already read the same list for a different reason.

Splitting for the sake of the number is not the point either. The six source
files that were over came apart along divisions they already carried - eighteen
section banners between `power.py` and `report_charts.py`, two of them stale -
and that is the test to apply: a file is ready to divide when its own comments
have already divided it, or when a group of its functions has one relationship
to the rest that the others do not share. `episode.py` came apart on the second
of those: four different relationships to an API call, only one of which makes
one.

## How work is expected to be checked

This is the part that most changes the quality of a contribution here.

**Plant the defect the test claims to catch.** A test that passes is not evidence;
a test that passes both before and after a fix proves nothing. Revert the fix,
watch the test fail, restore it. Several tests in this suite were found to be
non-discriminating exactly this way — one asserted on files that a different part
of the code writes, so it passed with the logic it was guarding removed.

**Write guards against the rule, not against a path.** This is the repeat defect
class here, and it fails by passing.

Ask what the guard is actually asserting. "This function must not print" is about
that function, and naming it is correct. "Text IO names its encoding" is a rule
about all code, and scoping it to one module means the other modules are
unguarded — which is exactly how that particular rule came to be fixed twice and
still left 49 sites uncovered. For the second kind, take the file list from
`conftest` (`source_python_files()`, `suite_python_files()`,
`project_python_files()`) so a module added later inherits the rule instead of
escaping it.

**A search over a named function's source is a guard against a location.**
Twelve checks here asserted that some call appeared in `inspect.getsource` of one
named function - that `run_batch` contained `confinement_available()`, that
`grader_ab.main` contained `graders_tag`, that `run_evaluation` contained `if
capability is None:`. Every one of them broke when the code it was about was
given a function of its own, while the behaviour it existed to protect was
untouched; and none of them would have noticed that same call being deleted from
a callee. Assert the behaviour instead: run the thing and read what it did.
`conftest.refused_rollout` returns the exit code, the output AND the number of
episodes attempted - and that third value is the one that matters, because a
refusal and a batch that starts and then fails both exit 1 and both print the
refusal.

Where the property really is structural, **walk the call graph rather than one
function's body**. "Every read mode reaches `settle_analysis`" and "no report
section is defined and never called" are both true through a callee, and both
guards were carrying a hand-written map of the indirections they knew about -
which is the same defect as a hand-written module list. Derive the reachable
set, and pair it with a check that the walk can still answer no: a reachability
test that always returns True passes with everything broken.

The same applies to a hand-written list of what to iterate over. The grading
package's guards enumerated their own submodules in a tuple; it fell two behind
the directory, and four guards silently stopped covering two modules. Derive the
list, and assert it is non-empty — a glob that matches nothing empties the scope
and every guard built on it passes.

Where existing debt makes a rule impossible to satisfy today, record it as a
baseline that is checked in **both** directions: nothing outside the list may
offend, and everything inside it must still offend. A one-directional baseline
becomes a permanent exemption; a two-directional one can only shrink, and tells
you to delete the entry when you fix the file. See
`TestNoFileIsReadOrWrittenAtTheLocalesMercy` in `test_project/test_project_files.py`.

**Check the REASON an exemption gives, not just the list.** The worst kind is not
debt honestly recorded - it is an exemption that claims the rule cannot apply.
One here excluded eight fields from "every re-derived field is actually
re-derived" because "the read modes pass a transcript this function does not
take"; the function had taken a transcript since the day it was written and used
it for eight derivations. Three of the eight were a real hole in the rule, and
the other five were not in the checked set at all, so exempting them subtracted
nothing and made the list look considered. An exemption's justification is a
factual claim about the code, and it rots exactly like a comment does - so read
it the same way: is this true, and does it say something the code cannot.

**Measure platform behaviour rather than reasoning about it.** Four defects in
recent versions were invisible on macOS and real on Linux. `sandbox-exec` execs
the shell in place; `bwrap` forks it. `tempfile.gettempdir()` is `/var/folders/...`
on macOS and `/tmp` on Linux, so a guard comparing against `"/tmp"` means
different things on each. CI runs Linux; a green local run is half the evidence.

**Avoid absolute wall-clock assertions.** They have to be tuned to one machine and
then flake on a slower one. Time a workload against the same workload run the other
way, and assert on the difference rather than the ratio, so per-run overhead cancels.

## Before you push

```bash
ruff check .                                 # the lint job; config in pyproject
SUBVERSIONBENCH_NO_SKIPS=1 pytest            # the suite job
coverage run -m pytest && coverage report    # the coverage job, floor in pyproject
```

`SUBVERSIONBENCH_NO_SKIPS=1` turns a skip for a missing optional dependency into a
failure, which is how the fully-installed CI job proves nothing quietly opted out.
Corpus-absent skips are still allowed.

If the printed report changes on purpose, regenerate its snapshots and read the
diff rather than trusting it:

```bash
SUBVERSIONBENCH_UPDATE_REPORT_SNAPSHOTS=1 pytest test_reporting/test_console.py
git diff report_snapshots/
```

## While an evaluation is running

Check first — `ps ax | grep run_eval` — because a batch takes hours and the
consequences are silent.

- **Do not run the test suite.** The harness enforces a 10 second per-command
  timeout with a 2 second SIGTERM grace. A full run spawns hundreds of sandboxed
  subprocesses, and the CPU contention can push a legitimate model command past
  that timeout, recording `Command timed out.` into a live transcript. That is
  contaminated data in the arm being collected.
- **Do not edit source.** Several modules import lazily inside functions, so a
  long-running process can pick up a half-edited codebase and execute mixed
  versions mid-episode.
- **Do not reinstall the package.**
- Documentation, and pushing so CI verifies remotely, are safe.

To stop a batch, use Ctrl-C or `kill <pid of run_all_arms.sh>`. Two traps here,
both measured:

- **Ctrl-Z does not stop it, it suspends it.** Nothing is spent while it sits
  there, so it looks stopped; the moment anything continues it every remaining
  arm runs and the script exits 0.
- **Ctrl-C is powerless if SIGINT was ignored when the script started**, which
  is what a background job of a non-interactive shell inherits. bash may not
  trap a signal it inherited as ignored, so only the arm's own process sees it.
  The script says so at startup when it detects this; `kill <pid>` works.

## Traps that have cost time

- **Never rewrite history unscoped.** `git filter-repo` with no `--refs` rewrites
  every branch, `main` included, even when the change targets one blob near the
  tip of a feature branch. At least one commit low in this history carries a
  `gpgsig` header, filter-repo strips signatures on re-import, and that one
  changed hash cascades to every descendant. Trees stay identical, so nothing
  looks wrong until branch hashes are compared — which is the check:

  ```bash
  git for-each-ref --format='%(refname:short) %(objectname)' refs/heads  # before
  git filter-repo --force --partial --refs <base>~1..<branch>            # scoped
  git for-each-ref --format='%(refname:short) %(objectname)' refs/heads  # after
  ```

  Every branch but the one named must come back with the hash it went in with.

  `gpg` is not installed here, so `%G?` errors rather than reporting; find
  signed commits with `git cat-file commit <sha> | grep '^gpgsig'`. Keep
  `origin` as the backup by not force-pushing until the comparison passes, and
  know that a force-push does **not** remove anything from GitHub: rewritten-away
  objects stay fetchable by full hash until GitHub Support purges them, so the
  push is the start of that request rather than the end of the job.
- `pytest.skip` raises `Skipped`, a `BaseException` subclass, so `except Exception`
  never catches it. Use `conftest.skip_without`, which raises `unittest.SkipTest`
  and is honoured by both runners.
- `run_tests.py` is a pytest-free runner and cannot interpret `@pytest.fixture`,
  `@pytest.mark.parametrize` or `@pytest.mark.usefixtures`. `test_project/test_dependencies.py`
  refuses them. Use a plain helper or a context manager.
- `ruff --fix` will strip re-exports from the two facade modules
  (`llm_client.py`, `grading/__init__.py`) and break collection immediately. Both
  are per-file-ignored for `F401`; the "safe" in "safe fix" is a claim about the
  transformation, not about the module's purpose.
- `zip()` truncates silently. Every call here states `strict=True` or
  `strict=False`; keep that up, and pick the one that is true rather than the one
  that passes.
- **Never assign to `args`.** One argparse Namespace is passed by reference into
  every callee, so a write is visible to the rest of the run - including the next
  iteration of a fan-out, which is how a batch collected at one effort level came
  to filter every later model to it and report success on a half-done backfill.
  Pass what a callee needs, or extend `BatchIdentity` (`subversionbench/batch.py`)
  which is frozen and built at the boundary for exactly this reason.
  `test_project/test_args_bag.py` enforces it, and also checks that every field read off the
  bag is one something can actually set - a misspelled `args.oversigh` is an
  AttributeError raised only on the branch that reaches it, hours into a batch.
- The Linux runner needs bubblewrap **and**
  `kernel.apparmor_restrict_unprivileged_userns=0`. The apt package alone leaves
  the runner looking equipped and unable to isolate anything, so CI asserts
  `confinement_available()` before running the suite.

## Ponytail, lazy senior dev mode

You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.

Before writing any code, stop at the first rung that holds:

1. Does this need to be built at all? (YAGNI)
2. Does it already exist in this codebase? Reuse the helper, util, or pattern that's already here, don't re-write it.
3. Does the standard library already do this? Use it.
4. Does a native platform feature cover it? Use it.
5. Does an already-installed dependency solve it? Use it.
6. Can this be one line? Make it one line.
7. Only then: write the minimum code that works.

The ladder runs after you understand the problem, not instead of it: read the task and the code it touches, trace the real flow end to end, then climb.

Bug fix = root cause, not symptom: a report names a symptom. Grep every caller of the function you touch and fix the shared function once — one guard there is a smaller diff than one per caller, and patching only the path the ticket names leaves a sibling caller still broken.

Rules:

- No abstractions that weren't explicitly requested.
- No new dependency if it can be avoided.
- No boilerplate nobody asked for.
- Deletion over addition. Boring over clever. Fewest files possible.
- Shortest working diff wins, but only once you understand the problem. The smallest change in the wrong place isn't lazy, it's a second bug.
- Question complex requests: "Do you actually need X, or does Y cover it?"
- Pick the edge-case-correct option when two stdlib approaches are the same size, lazy means less code, not the flimsier algorithm.
- Mark deliberate simplifications that cut a real corner with a known ceiling (global lock, O(n²) scan, naive heuristic) with a `ponytail:` comment naming the ceiling and upgrade path.

Not lazy about: understanding the problem (read it fully and trace the real flow before picking a rung, a small diff you don't understand is just laziness dressed up as efficiency), input validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs (the platform is never the spec ideal, a clock drifts, a sensor reads off), anything explicitly requested. Lazy code without its check is unfinished: non-trivial logic leaves ONE runnable check behind, the smallest thing that fails if the logic breaks (an assert-based demo/self-check or one small test file; no frameworks, no fixtures). Trivial one-liners need no test.

*Imported from `github.com/DietrichGebert/ponytail/AGENTS.md`. The text is
verbatim with two changes: the heading is demoted so this file keeps a single
`#`, and the closing line - "Yes, this file also applies to agents working on
the ponytail repo itself. Especially to them." - is dropped, being about that
repository rather than this one.*

### Where this and the rules above disagree

The ladder, the root-cause rule and the `ponytail:` ceiling comment sit well
beside what is already here. Four lines do not, and the rules above win,
because each of them was written down after a defect got through:

- **"no frameworks, no fixtures".** This suite is pytest and leans on shared
  fixtures deliberately - `conftest.batch_episode`, `report_fixtures._write_episode`,
  `conftest.refused_rollout`. Bespoke per-test builders are what produced the two
  fixtures that asserted impossible states, so "reuse the helper that is already
  here" argues FOR the fixtures rather than against them.
- **"ONE runnable check".** One check cannot express the rules this repository
  actually needs: a baseline checked in both directions, a guard written against
  the rule rather than one path, or a plant showing the check fails against the
  defect it names. Where one check does express the rule, one is right.
- **"deletion over addition"** does not reach the comments that record a
  defect and its measurement. Those are the reason a simplification cannot be
  made again, and "The shape of the code" above says to keep them.
- **"no abstractions that weren't explicitly requested"** is not a bar on
  splitting a function that has grown a section-header comment, or a file over
  the limit. Those splits follow divisions the code already carries, which is a
  different act from inventing an abstraction nobody asked for.

Everything in the "Hard invariants" section is outside this negotiation
entirely: no reading of "shortest working diff wins" licenses moving a rollout
fingerprint, putting scenario text in a tracked file, or touching a credential.
