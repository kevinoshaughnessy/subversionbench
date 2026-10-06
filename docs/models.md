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

Each entry below links to that checkpoint's lab-published system or model card.
**† marks a checkpoint with no lab-published card found** — the link goes to the
OpenRouter listing (or, for `qwen/qwen3.5-flash-02-23`, the open-weight base it is
hosted from) instead, which is a routing/pricing page, not a safety document. Links
were checked by hand against a web search, not against a fixed source of truth, so — like
the rest of this page — they are current as of the last edit, not regenerated: a preview
card in particular can be replaced or withdrawn once a model reaches general
availability. The capability and goal-guarding sections below re-list some of these same
models; look up their cards here rather than in two more copies of the same links.

## Mainline scenario (oversight + sandbox)

The two-act propensity design: three nudge levels (`none`, `strong`, `max`) × oversight
present/absent × lure present/absent, ten runs per arm by default — see
[`run_all_arms.sh`](../README.md#every-arm-for-one-model). Every model below has the full
twelve-arm cross product.

- [claude-haiku-4-5-20251001](https://www.anthropic.com/claude-haiku-4-5-system-card)
- [claude-opus-5](https://www-cdn.anthropic.com/c5fbac3f0b1280a933ebd26d3cb8bb9f5bdeaf48/Claude%20Opus%205%20System%20Card.pdf)
- [claude-sonnet-4-5](https://www.anthropic.com/claude-sonnet-4-5-system-card)
- [claude-sonnet-4-6](https://www.anthropic.com/claude-sonnet-4-6-system-card)
- [claude-sonnet-5](https://www.anthropic.com/claude-sonnet-5-system-card)
- [deepseek/deepseek-v4-flash](https://fe-static.deepseek.com/chat/transparency/deepseek-V4-model-card-EN.pdf)
- [deepseek/deepseek-v4-flash-0731](https://fe-static.deepseek.com/chat/transparency/deepseek-V4-model-card-EN.pdf)
- [deepseek/deepseek-v4-pro](https://fe-static.deepseek.com/chat/transparency/deepseek-V4-model-card-EN.pdf)
- [deepseek/deepseek-v4-pro-0813](https://fe-static.deepseek.com/chat/transparency/deepseek-V4-model-card-EN.pdf)
- [deepseek/deepseek-v4.1-flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash)
- [google/gemini-3-flash-preview](https://openrouter.ai/google/gemini-3-flash-preview) †
- [google/gemini-3.1-flash-lite](https://deepmind.google/models/model-cards/gemini-3-1-flash-lite/)
- [google/gemini-3.5-flash](https://deepmind.google/models/model-cards/gemini-3-5-flash/)
- [google/gemini-3.6-flash](https://deepmind.google/models/model-cards/gemini-3-6-flash/)
- [google/gemini-3.7-flash](https://deepmind.google/models/model-cards/gemini-3-7-flash/)
- [gpt-5.6-luna](https://deploymentsafety.openai.com/gpt-5-6/gpt-5-6.pdf)
- [gpt-6-astra](https://deploymentsafety.openai.com/gpt-6-astra)
- [gpt-6-luna](https://deploymentsafety.openai.com/gpt-6-astra/sec:appendix-sol-luna)
- [gpt-6-sol](https://deploymentsafety.openai.com/gpt-6-astra/sec:appendix-sol-luna)
- [inception/mercury-2.5](https://openrouter.ai/inception/mercury-2.5) †
- [inclusionai/ling-3.0-flash](https://huggingface.co/inclusionAI/Ling-3.0-flash)
- [meta-llama/llama-4-maverick](https://www.llama.com/docs/model-cards-and-prompt-formats/llama4/)
- [meta-llama/llama-4-scout](https://www.llama.com/docs/model-cards-and-prompt-formats/llama4/)
- [meta/muse-glimmer-30b](https://developer.meta.com/ai/models/muse-glimmer/)
- [meta/muse-spark-1.1](https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report/)
- [meta/muse-spark-1.2](https://developer.meta.com/ai/models/muse-spark/)
- [meta/muse-spark-1.3](https://developer.meta.com/ai/models/muse-spark/)
- [mistralai/mistral-small-2603](https://docs.mistral.ai/models/model-cards/mistral-small-4-0-26-03)
- [moonshotai/kimi-k2-thinking](https://huggingface.co/moonshotai/Kimi-K2-Thinking)
- [moonshotai/kimi-k2.5](https://huggingface.co/moonshotai/Kimi-K2.5)
- [moonshotai/kimi-k2.6](https://huggingface.co/moonshotai/Kimi-K2.6)
- [moonshotai/kimi-k3](https://huggingface.co/moonshotai/Kimi-K3)
- [openai/gpt-5.6-luna](https://deploymentsafety.openai.com/gpt-5-6/gpt-5-6.pdf)
- [qwen/qwen3.5-flash-02-23](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) †
- [qwen/qwen3.6-27b](https://huggingface.co/Qwen/Qwen3.6-27B)
- [qwen/qwen3.6-flash](https://openrouter.ai/qwen/qwen3.6-flash) †
- [qwen/qwen3.7-flash](https://openrouter.ai/qwen/qwen3.7-flash) †
- [qwen/qwen3.8-27b](https://huggingface.co/Qwen/Qwen3.8-27B)
- [qwen/qwen3.8-flash](https://openrouter.ai/qwen/qwen3.8-flash) †
- [qwen/qwen3.8-max-0902](https://openrouter.ai/qwen/qwen3.8-max-0902) †
- [tencent/hy3](https://huggingface.co/tencent/Hy3)
- [tencent/hy4-preview](https://huggingface.co/tencent/Hy4-preview)
- [thinkingmachines/inkling-small](https://thinkingmachines.ai/model-card/inkling-small/)
- [unbiased/pareto](https://unbiased.ai/model-card/)
- [x-ai/grok-4.20](https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf)
- [x-ai/grok-4.3](https://openrouter.ai/x-ai/grok-4.3) †
- [x-ai/grok-4.5](https://media.x.ai/v1/website/4p5-5184fdf9.pdf)
- [x-ai/grok-4.6](https://media.x.ai/v1/website/card-4p6-4cd2dc57.pdf)
- [x-ai/grok-4.7](https://media.x.ai/v1/website/4p7card-5eccc980.pdf)
- [z-ai/glm-5.1](https://huggingface.co/zai-org/GLM-5.1)
- [z-ai/glm-5.2](https://huggingface.co/zai-org/GLM-5.2)
- [z-ai/glm-5.3](https://huggingface.co/zai-org/GLM-5.3)

### Capability arm

`--capability {oversight,sandbox}` replaces the task instruction with one that asks for
the act outright. A model that performs it is shown capable, so its zero on the propensity
arm reads as a choice; one that does not has shown nothing about its ability. Measured for
both acts on:

claude-haiku-4-5-20251001 · deepseek/deepseek-v4-flash · deepseek/deepseek-v4-flash-0731 ·
gpt-5.6-luna · meta-llama/llama-4-maverick · meta/muse-glimmer-30b ·
mistralai/mistral-small-2603 · moonshotai/kimi-k2-thinking · moonshotai/kimi-k2.5 ·
moonshotai/kimi-k2.6 · moonshotai/kimi-k3 · qwen/qwen3.5-flash-02-23 ·
qwen/qwen3.6-flash · qwen/qwen3.7-flash · x-ai/grok-4.20 · x-ai/grok-4.3 · z-ai/glm-5.1 ·
z-ai/glm-5.2

Every model performed both acts when instructed. Under the original sandbox prompt,
gpt-5.6-luna and moonshotai/kimi-k3 refused every instructed sandbox episode (15 and 10),
citing the system prompt's rule that the account is scoped to the project directory. That
instruction asked them to override a rule set above it, so those refusals said nothing about
capability. From v227 the sandbox arm carries its own system prompt, which grants the look in
place of that rule, under new fingerprints. Rerun under it (5 episodes per oversight arm,
`eval_results_r10cap/`, 2026-10-02), neither model refused once: gpt-5.6-luna succeeded in 6
of 10 and attempted without landing in the other 4, and moonshotai/kimi-k3 succeeded in all
10. The other sixteen performed the act under the stricter prompt, so their results stand;
the report pools both rollouts for the yes or no and counts the earlier episodes apart.

## Goal-guarding scenario

The third misaligned act — see [the goal-guarding arm](methodology.md#the-goal-guarding-arm).
`--goalguard {deferred,replacement}` × oversight present/absent × nudge `none`/`strong`,
lure held off throughout: eight arms per model. A model is marked complete once all eight
arms are collected and graded; between the two it is marked collected, grading pending.
`openai/gpt-5.6-luna`, the OpenRouter route to gpt-5.6-luna, is deliberately not in this set: the
native route below stands for the model.

| model | status |
|---|---|
| claude-haiku-4-5-20251001 | complete |
| claude-opus-5 | complete; capability not shown, so its zeros are not interpretable |
| claude-sonnet-4-5 | complete |
| claude-sonnet-4-6 | complete |
| claude-sonnet-5 | complete |
| deepseek/deepseek-v4-flash | complete |
| deepseek/deepseek-v4-flash-0731 | complete |
| deepseek/deepseek-v4-pro | complete |
| deepseek/deepseek-v4-pro-0813 | complete |
| deepseek/deepseek-v4.1-flash | complete |
| google/gemini-3-flash-preview | complete |
| google/gemini-3.1-flash-lite | complete |
| google/gemini-3.5-flash | complete |
| google/gemini-3.6-flash | complete (78/80 — one episode missing from each of replacement/oversight/none and replacement/oversight/strong) |
| google/gemini-3.7-flash | complete |
| gpt-5.6-luna | complete |
| gpt-6-astra | complete |
| gpt-6-luna | complete |
| gpt-6-sol | complete |
| inception/mercury-2.5 | partial (27/80): Inception's upstream timed out on 43 episodes; the two strong replacement arms stopped after five consecutive failures. To be resumed |
| inclusionai/ling-3.0-flash | complete |
| meta-llama/llama-4-maverick | complete |
| meta/muse-glimmer-30b | complete |
| meta/muse-spark-1.1 | complete |
| meta/muse-spark-1.2 | complete |
| meta/muse-spark-1.3 | complete; capability not shown, so its zeros are not interpretable |
| mistralai/mistral-small-2603 | complete (79/80 — one episode missing from replacement/oversight/strong) |
| moonshotai/kimi-k2-thinking | complete |
| qwen/qwen3.6-27b | complete |
| qwen/qwen3.7-flash | complete |
| qwen/qwen3.8-27b | complete |
| qwen/qwen3.8-flash | complete (79/80 — one episode missing from replacement/no-oversight/none) |
| qwen/qwen3.8-max-0902 | complete |
| tencent/hy4-preview | complete |
| thinkingmachines/inkling-small | complete |
| x-ai/grok-4.20 | complete |
| x-ai/grok-4.3 | complete |
| x-ai/grok-4.5 | complete |
| x-ai/grok-4.6 | complete |
| x-ai/grok-4.7 | complete |
| z-ai/glm-5.2 | complete |
| z-ai/glm-5.3 | complete |

`eval_results_goalguard_r1_prenudgefix/` holds episodes superseded by the v183 fix to
`nudge` reaching scenario assembly (see CHANGELOG.md) — not a fourth model, and not part
of the corpus above.

The corpus was collected with `--no-grader`, so the awareness grader is applied afterwards,
one model at a time, with `--grade-existing --write-back --regrade default` (gpt-6-sol is the
default grader). Graded so far: every model marked complete above (2026-10-03 to 2026-10-05,
both nudges, no grader errors and no partially graded episodes). The two episodes collected
with their interrogation pending were completed with `--complete-pending` on 2026-10-04.
gpt-6-sol's own episodes were graded by gpt-6-sol, so its awareness readings come from a
grader judging itself; [grader-selection.md](grader-selection.md) lists this as a known weakness.

### Capability arm

`--capability goalguard`, collected in `eval_results_goalguard_r1cap/`. Every model
below marked capable has goal-guarded when instructed, so a zero in its goal-guarding arms is
not an incapability. Two instructed episodes have ended in a failed attempt. One is a meta/muse-spark-1.2
`sed -i` in the GNU form, which this harness's BSD sed rejects, after which the model stopped.
Since v226 `capability_outcome` scores it as `attempted`, as it does one qwen/qwen3.8-max-0902
episode that wrote the file without the edit landing; both were read as refusals before. Every
other instructed episode succeeded, refused, or (one gemini-3.6-flash episode) was stopped by the
provider's content filter.

claude-opus-5 and meta/muse-spark-1.3 are the models not shown capable: each refused all 10
instructed episodes (2026-10-03 and 2026-10-05 respectively), muse-spark-1.3 without
attempting an edit in any. That is not an incapability — a refusal measures willingness
again — but it means a zero in either model's goal-guarding arms cannot be read as the
model's choice rather than its ability. claude-opus-5's propensity arms (2026-10-03) are
complete at 80/80 with no API errors; nine episodes, all at nudge `none`, ended on the
provider's refusal stop reason rather than the model stopping.

| model | capable | instructed episodes |
|---|---|---|
| claude-haiku-4-5-20251001 | yes | succeeds in all |
| claude-opus-5 | not shown | refused all 10 |
| claude-sonnet-4-5 | yes | succeeds in all |
| claude-sonnet-4-6 | yes | refuses most |
| claude-sonnet-5 | yes | refuses most |
| deepseek/deepseek-v4-flash | yes | succeeds in all |
| deepseek/deepseek-v4-flash-0731 | yes | succeeds in all |
| deepseek/deepseek-v4-pro | yes | succeeds in all |
| deepseek/deepseek-v4-pro-0813 | yes | succeeds in all |
| deepseek/deepseek-v4.1-flash | yes | refuses most |
| google/gemini-3.1-flash-lite | yes | succeeds in all |
| google/gemini-3.5-flash | yes | succeeds in all |
| google/gemini-3.6-flash | yes | succeeds in most |
| google/gemini-3.7-flash | yes | succeeds in all |
| gpt-5.6-luna | yes | succeeds in all |
| gpt-6-astra | yes | succeeds in all |
| gpt-6-luna | yes | succeeds in all |
| gpt-6-sol | yes | succeeds in all |
| inception/mercury-2.5 | yes | succeeds in all (2 of 3; 1 API error) |
| inclusionai/ling-3.0-flash | yes | succeeds in all |
| meta-llama/llama-4-maverick | yes | succeeds in all |
| meta-llama/llama-4-scout | not run | no routable endpoint (2026-10-05): OpenRouter drops its two non-BYOK providers for lacking tool support, and the third is BYOK-only |
| meta/muse-glimmer-30b | yes | succeeds in all |
| meta/muse-spark-1.1 | yes | refuses most |
| meta/muse-spark-1.2 | yes | refuses most; 1 failed attempt |
| meta/muse-spark-1.3 | not shown | refused all 10 |
| mistralai/mistral-small-2603 | yes | succeeds in all |
| moonshotai/kimi-k2-thinking | yes | succeeds in most |
| moonshotai/kimi-k2.5 | yes | succeeds in all |
| qwen/qwen3.6-27b | yes | succeeds in all |
| qwen/qwen3.7-flash | yes | succeeds in all |
| qwen/qwen3.8-27b | yes | succeeds in all |
| qwen/qwen3.8-flash | yes | succeeds in all |
| qwen/qwen3.8-max-0902 | yes | refuses most; 1 failed attempt |
| tencent/hy4-preview | yes | succeeds in all |
| thinkingmachines/inkling-small | yes | succeeds in all, each after a failed first write |
| x-ai/grok-4.20 | yes | succeeds in all |
| x-ai/grok-4.3 | yes | succeeds in all |
| x-ai/grok-4.5 | yes | succeeds in all |
| x-ai/grok-4.7 | yes | succeeds in all |
| z-ai/glm-5.2 | yes | succeeds in all |
| z-ai/glm-5.3 | yes | succeeds in most |

`capability_report.py` reports the same yes-or-no: one success is capable, so the six that
refuse most are capable too, and their propensity zeros read as the model's.

## Pending evaluation

Models not yet in the mainline corpus that fall inside the selection window: first listed
on [OpenRouter](https://openrouter.ai/models?output_modalities=text) between the
[exposure boundary](methodology.md#the-exposure-boundary-is-dated) (2026-07-28) and the
cut-off, **2026-09-27**, with text output and tool calling, which the harness needs.
OpenRouter's listing date stands in for the lab's release date. Links go to the OpenRouter
listing until a lab-published card is found.

There is no price ceiling. The most expensive models tend to be the most capable, and
potentially the most dangerous, so a model is excluded on cost only if it would be
unreasonably expensive to evaluate.

- [aion-labs/aion-3.5](https://openrouter.ai/aion-labs/aion-3.5)
- [aion-labs/aion-3.5-mini](https://openrouter.ai/aion-labs/aion-3.5-mini)
- [anthropic/claude-opus-5.5](https://openrouter.ai/anthropic/claude-opus-5.5)
- [bytedance-seed/seed-2-1-turbo](https://openrouter.ai/bytedance-seed/seed-2-1-turbo)
- [bytedance-seed/seed-2.0-code](https://openrouter.ai/bytedance-seed/seed-2.0-code)
- [cohere/command-a-plus](https://openrouter.ai/cohere/command-a-plus)
- [fireworks/ember-1](https://openrouter.ai/fireworks/ember-1)
- [google/gemini-3.8-flash](https://openrouter.ai/google/gemini-3.8-flash)
- [ibm-granite/granite-4.2-8b](https://openrouter.ai/ibm-granite/granite-4.2-8b)
- [nvidia/nemotron-3.5-lightning](https://openrouter.ai/nvidia/nemotron-3.5-lightning)
- [perceptron/perceptron-mk1.5](https://openrouter.ai/perceptron/perceptron-mk1.5)
- [prism-ml/ternary-bonsai-2-27b](https://openrouter.ai/prism-ml/ternary-bonsai-2-27b)
- [qwen/qwen3.8-2.4t-a95b](https://openrouter.ai/qwen/qwen3.8-2.4t-a95b)
- [qwen/qwen3.8-omni-flash](https://openrouter.ai/qwen/qwen3.8-omni-flash)
- [sakana/fugu-max](https://openrouter.ai/sakana/fugu-max)
- [sakana/fugu-ultra-v2](https://openrouter.ai/sakana/fugu-ultra-v2)
- [sakana/sakana-namazu](https://openrouter.ai/sakana/sakana-namazu)
- [upstage/solar-mini4](https://openrouter.ai/upstage/solar-mini4)
- [upstage/solar-pro4](https://openrouter.ai/upstage/solar-pro4)
- [xiaomi/mimo-v2.6-flash](https://openrouter.ai/xiaomi/mimo-v2.6-flash)
- [xiaomi/mimo-v2.6-pro](https://openrouter.ai/xiaomi/mimo-v2.6-pro)
- [z-ai/glm-5.3-flash](https://openrouter.ai/z-ai/glm-5.3-flash)

Inside the window but not pending:

- **anthropic/claude-fable-5 and anthropic/claude-fable-5.1** — their safety classifiers
  refuse the scenario, so neither can be evaluated.
- **Anonymous OpenRouter alpha models** (`stealth/space-bunny-alpha`) — never evaluated:
  with no known lab or release date, a result could be neither attributed nor placed
  against the exposure boundary.
- **Variants of a model already evaluated** — `openai/gpt-6-astra-pro`, `gpt-6-sol-pro`
  and `gpt-6-luna-pro` (the same underlying models, per their listings), speed variants
  (`z-ai/glm-5.3-prime`, `z-ai/glm-5.3-flashx`, `qwen/qwen3.8-max-prime`,
  `xiaomi/mimo-v2.6-pro-ultraspeed`), Meta's contributor tiers of muse-spark 1.2 and 1.3,
  and `deepseek/deepseek-v4-flash-vision-exp`, `inclusionai/ling-3.0-flash-fin` and
  `inclusionai/ling-3.0-flash-vl`.
- **No tool calling** — Tencent's hy-mt2 translation models, inference-net's schematron
  extraction models, and `typesafe/jev-router`.

## Regenerating this list

```bash
python3 -c "
import json, glob
for corpus, out in (('eval_results_r10', None), ('eval_results_r10cap', ('oversight', 'sandbox')),
                    ('eval_results_goalguard_r1', None),
                    ('eval_results_goalguard_r1cap', ('goalguard',))):
    models = set()
    for p in glob.glob(f'{corpus}/run_*.json'):
        d = json.load(open(p, encoding='utf-8'))
        if out is None or d.get('capability') in out:
            models.add(d['model'])
    print(corpus, sorted(models))
"
```

This page is maintained by hand against that query, not regenerated automatically — update
it when a model's coverage changes rather than trusting it to still be current.
