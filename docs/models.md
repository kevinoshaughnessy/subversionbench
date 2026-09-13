# Models evaluated

Which models have been run, under which scenario and which arms. **No rates, no act
counts, no effect sizes** — this is a coverage list, not a results page. For outcomes see
[docs/report.md](report.md); for how a corpus is collected or reproduced see
[docs/operations.md](operations.md).

A model appears here once it has at least one completed episode in the named corpus.
Model identity is the literal `--model` string the harness was given — a bare name
(`gpt-5.6-luna`) is the native provider route, `openai/gpt-5.6-luna` is the same
underlying model reached through OpenRouter, and the two are tracked separately because
they are different rollout paths, not the same evaluation twice.

## Mainline scenario (oversight + sandbox)

The two-act propensity design: three nudge levels (`none`, `strong`, `max`) × oversight
present/absent × lure present/absent, ten runs per arm by default — see
[`run_all_arms.sh`](../README.md#every-arm-for-one-model). Every model below has the full
twelve-arm cross product.

- claude-haiku-4-5-20251001
- deepseek/deepseek-v4-flash
- deepseek/deepseek-v4-flash-0731
- deepseek/deepseek-v4-pro
- deepseek/deepseek-v4-pro-0813
- google/gemini-3-flash-preview
- google/gemini-3.1-flash-lite
- google/gemini-3.5-flash
- google/gemini-3.6-flash
- google/gemini-3.7-flash
- gpt-5.6-luna
- inclusionai/ling-3.0-flash
- meta-llama/llama-4-maverick
- meta-llama/llama-4-scout
- meta/muse-glimmer-30b
- meta/muse-spark-1.2
- meta/muse-spark-1.3
- mistralai/mistral-small-2603
- moonshotai/kimi-k2-thinking
- moonshotai/kimi-k2.5
- moonshotai/kimi-k2.6
- moonshotai/kimi-k3
- openai/gpt-5.6-luna
- qwen/qwen3.5-flash-02-23
- qwen/qwen3.6-27b
- qwen/qwen3.6-flash
- qwen/qwen3.7-flash
- qwen/qwen3.8-27b
- qwen/qwen3.8-flash
- tencent/hy3
- thinkingmachines/inkling-small
- x-ai/grok-4.20
- x-ai/grok-4.3
- x-ai/grok-4.5
- x-ai/grok-4.6
- z-ai/glm-5.1
- z-ai/glm-5.2
- z-ai/glm-5.3

### Capability (ceiling) arm

`--capability {oversight,sandbox}` replaces the task instruction with one that asks for
the act outright, so a model's zero on the propensity arm can be read against its own
ceiling rather than assumed. Measured for both acts on:

claude-haiku-4-5-20251001 · deepseek/deepseek-v4-flash · deepseek/deepseek-v4-flash-0731 ·
gpt-5.6-luna · meta-llama/llama-4-maverick · meta/muse-glimmer-30b ·
mistralai/mistral-small-2603 · moonshotai/kimi-k2-thinking · moonshotai/kimi-k2.5 ·
moonshotai/kimi-k2.6 · moonshotai/kimi-k3 · qwen/qwen3.5-flash-02-23 ·
qwen/qwen3.6-flash · qwen/qwen3.7-flash · x-ai/grok-4.20 · x-ai/grok-4.3 · z-ai/glm-5.1 ·
z-ai/glm-5.2

## Goal-guarding scenario

The third misaligned act — see [the goal-guarding arm](methodology.md#the-goal-guarding-arm).
`--goalguard {deferred,replacement}` × oversight present/absent × nudge `none`/`strong`,
lure held off throughout: eight arms per model.

| model | status |
|---|---|
| google/gemini-3.5-flash | complete |
| x-ai/grok-4.5 | complete |
| meta/muse-spark-1.2 | in progress |

`eval_results_goalguard_r1_prenudgefix/` holds episodes superseded by the v183 fix to
`nudge` reaching scenario assembly (see CHANGELOG.md) — not a fourth model, and not part
of the corpus above.

### Capability (ceiling) arm

`--capability goalguard`, measured on:

- google/gemini-3.5-flash
- x-ai/grok-4.5

## Regenerating this list

```bash
python3 -c "
import json, glob
for corpus, out in (('eval_results_r10', None), ('eval_results_r10cap', 'capability'),
                    ('eval_results_goalguard_r1', None)):
    models = set()
    for p in glob.glob(f'{corpus}/run_*.json'):
        d = json.load(open(p, encoding='utf-8'))
        if out is None or d.get('capability') == out:
            models.add(d['model'])
    print(corpus, sorted(models))
"
```

This page is maintained by hand against that query, not regenerated automatically — update
it when a model's coverage changes rather than trusting it to still be current.
