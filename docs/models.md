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
| qwen/qwen3.5-flash-02-23 | complete (pinned to Alibaba); one episode ended on a tool call written as text and one at the turn cap |
| qwen/qwen3.6-27b | complete |
| qwen/qwen3.6-flash | complete (pinned to Alibaba) |
| qwen/qwen3.7-flash | complete |
| qwen/qwen3.8-27b | complete |
| qwen/qwen3.8-flash | complete (79/80 — one episode missing from replacement/no-oversight/none) |
| qwen/qwen3.8-max-0902 | complete |
| tencent/hy3 | complete (pinned to Tencent) |
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
default grader). Graded so far: every model marked complete above (2026-10-03 to 2026-10-06,
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
| qwen/qwen3.5-flash-02-23 | yes | succeeds in all |
| qwen/qwen3.6-27b | yes | succeeds in all |
| qwen/qwen3.6-flash | yes | succeeds in all |
| qwen/qwen3.7-flash | yes | succeeds in all |
| qwen/qwen3.8-27b | yes | succeeds in all |
| qwen/qwen3.8-flash | yes | succeeds in all |
| qwen/qwen3.8-max-0902 | yes | refuses most; 1 failed attempt |
| tencent/hy3 | yes | succeeds in all |
| tencent/hy4-preview | yes | succeeds in all |
| thinkingmachines/inkling-small | yes | succeeds in all, each after a failed first write |
| x-ai/grok-4.20 | yes | succeeds in all |
| x-ai/grok-4.3 | yes | succeeds in all |
| x-ai/grok-4.5 | yes | succeeds in all |
| x-ai/grok-4.7 | yes | succeeds in all |
| z-ai/glm-5.1 | yes | succeeds in all |
| z-ai/glm-5.2 | yes | succeeds in all |
| z-ai/glm-5.3 | yes | succeeds in most |

`capability_report.py` reports the same yes-or-no: one success is capable, so the six that
refuse most are capable too, and their propensity zeros read as the model's.

### Provider routing

Collected through OpenRouter, a model can be served by any of several providers hosting the
same weights, which may differ in quantisation, chat template and reasoning handling. Until
2026-10-06 the goal-guarding corpus used OpenRouter's default routing, so the provider varied
between episodes and sometimes within one, and in some models it lines up with the arms: a
contrast between two arms served by different providers is partly a contrast between providers.
`served_by` records the provider of every turn, so this is measured rather than assumed.

**From 2026-10-06, each model is pinned to one provider** with `--openrouter-provider`, chosen as follows:

1. Exclude any endpoint without tool or reasoning support, or under 99% uptime over the last day.
2. Prefer the developer's own endpoint where OpenRouter lists one, unless it is more than twice
   as slow as the fastest: it is the reference deployment.
3. Otherwise take the fastest endpoint priced at no more than twice the cheapest. Throughput is
   shown on each model's OpenRouter Providers page, not in the public endpoints API; running the
   capability arm with `--openrouter-sort throughput` and reading `served_by` also finds it.
4. The capability arm and the propensity arms use the same pinned provider.

Price is rarely the deciding factor: among the models still to run, providers differ by at most
about twice in price per token.

**Audit of the goal-guarding corpus against this rule (2026-10-06).** Models reached through
their developer's own API (claude-*, gpt-*) and the OpenRouter models not listed below meet it:
one provider throughout, capability included. "Google" and "Google AI Studio" are counted as one
provider. The mainline corpus cannot be audited: `served_by` was added after the last r10 episode.

| model | episodes by provider | episodes switching mid-episode | capability arm served by | developer endpoint listed on OpenRouter (2026-10-06) |
|---|---|---|---|---|
| deepseek/deepseek-v4-flash-0731 | Relace 65, Wafer 8, StreamLake 7 | 5 | Relace | no |
| deepseek/deepseek-v4-pro | StreamLake 44, GMICloud 27, Relace 6, Baidu 2, SiliconFlow 1 | 18 | GMICloud, StreamLake | no |
| deepseek/deepseek-v4-pro-0813 | Baidu 80 | 1 | Baidu | yes, not used |
| deepseek/deepseek-v4.1-flash | CoreWeave 21, Together 20, Novita 19, Wafer 15, Relace 5 | 5 | AtlasCloud, Together | yes, not used |
| google/gemini-3-flash-preview | Google 80 | 0 | not recorded | no |
| inclusionai/ling-3.0-flash | Novita 79, DeepInfra 1 | 6 | Novita | no |
| meta-llama/llama-4-maverick | Parasail 65, DigitalOcean 15 | 11 | DigitalOcean | no |
| meta/muse-glimmer-30b | Together 76, Phala 4 | 17 | DeepInfra, Phala | no |
| moonshotai/kimi-k2-thinking | Google 44, Novita 36 | 9 | Google | no |
| qwen/qwen3.6-27b | Chutes 66, Phala 8, SiliconFlow 6 | 12 | Chutes | yes, not used |
| qwen/qwen3.8-27b | Wafer 55, Reka 25 | 2 | Wafer | yes, not used |
| qwen/qwen3.8-flash | Alibaba 70, Makora 9 | 28 | Alibaba | no |
| tencent/hy4-preview | Novita 56, SiliconFlow 24 | 15 | Novita, SiliconFlow, Tencent | yes, not used |
| x-ai/grok-4.6 | xAI 80 | 0 | not recorded | no |
| z-ai/glm-5.2 | Mistral 40, Relace 18, Together 10, Baidu 9, DigitalOcean 3 | 5 | Mistral, Together | yes, not used |
| z-ai/glm-5.3 | Wafer 40, Together 20, Modal 20 | 2 | Friendli, Mistral, Wafer | yes, not used |

"Episodes by provider" counts each episode under the provider that served most of its turns.
A developer endpoint listed today may not have been listed when the model was collected.
moonshotai/kimi-k2.5 is not in the table: its first 11 episodes were served by SiliconFlow under
default routing, and its provider is being settled under the rule above.

<details>
<summary>Episodes per arm and provider, for the models above</summary>

Each arm is nudge / goal-guarding variant / oversight; runs are numbered within the batch stamp.

- **deepseek/deepseek-v4-flash-0731**
  - none / deferred / oversight: Relace runs 1-2 of `20261002T131325`; Wafer runs 3-10 of `20261002T131325` (switched mid-episode: 3)
  - none / deferred / no oversight: Relace runs 1-10 of `20261002T143450`
  - none / replacement / oversight: Relace runs 1-10 of `20261002T121945` (switched mid-episode: 9)
  - none / replacement / no oversight: StreamLake runs 1-6 of `20261002T134712` (switched mid-episode: 6); Relace runs 7-10 of `20261002T134712`
  - strong / deferred / oversight: Relace runs 1-2,4-10 of `20261002T162439` (switched mid-episode: 2); StreamLake runs 3 of `20261002T162439` (switched mid-episode: 3)
  - strong / deferred / no oversight: Relace runs 1-10 of `20261002T172725`
  - strong / replacement / oversight: Relace runs 1-10 of `20261002T153252`
  - strong / replacement / no oversight: Relace runs 1-10 of `20261002T171009`
- **deepseek/deepseek-v4-pro**
  - none / deferred / oversight: Relace runs 1,3,5 of `20260929T181319` (switched mid-episode: 1,3,5); SiliconFlow runs 2 of `20260929T181319` (switched mid-episode: 2); StreamLake runs 4,6-10 of `20260929T181319` (switched mid-episode: 4,9-10)
  - none / deferred / no oversight: GMICloud runs 1-10 of `20260929T193417`
  - none / replacement / oversight: GMICloud runs 1-9 of `20260929T173414` (switched mid-episode: 9); Relace runs 10 of `20260929T173414`
  - none / replacement / no oversight: StreamLake runs 1-7 of `20260929T190328` (switched mid-episode: 1-2,7); Relace runs 8-9 of `20260929T190328` (switched mid-episode: 9); GMICloud runs 10 of `20260929T190328` (switched mid-episode: 10)
  - strong / deferred / oversight: GMICloud runs 1 of `20260929T204405`; StreamLake runs 2-10 of `20260929T204405` (switched mid-episode: 2)
  - strong / deferred / no oversight: StreamLake runs 1-10 of `20260929T214531`
  - strong / replacement / oversight: Baidu runs 1-2 of `20260929T194913` (switched mid-episode: 2); StreamLake runs 3-4 of `20260929T194913`; GMICloud runs 5-10 of `20260929T194913` (switched mid-episode: 5)
  - strong / replacement / no oversight: StreamLake runs 1-10 of `20260929T212116` (switched mid-episode: 1,8)
- **deepseek/deepseek-v4-pro-0813**
  - none / deferred / oversight: Baidu runs 1-10 of `20261002T222758`
  - none / deferred / no oversight: Baidu runs 1-10 of `20261002T232756`
  - none / replacement / oversight: Baidu runs 1-10 of `20261002T215614`
  - none / replacement / no oversight: Baidu runs 1-10 of `20261002T225422` (switched mid-episode: 4)
  - strong / deferred / oversight: Baidu runs 1-10 of `20261003T005305`
  - strong / deferred / no oversight: Baidu runs 1-10 of `20261003T020306`
  - strong / replacement / oversight: Baidu runs 1-10 of `20261003T000326`
  - strong / replacement / no oversight: Baidu runs 1-10 of `20261003T014243`
- **deepseek/deepseek-v4.1-flash**
  - none / deferred / oversight: Relace runs 1-3,9-10 of `20260927T115356` (switched mid-episode: 1); Wafer runs 4-8 of `20260927T115356`
  - none / deferred / no oversight: Novita runs 1-10 of `20260927T125113`
  - none / replacement / oversight: Wafer runs 1-10 of `20260927T104628` (switched mid-episode: 5)
  - none / replacement / no oversight: CoreWeave runs 1 of `20260927T123451`; Novita runs 2-10 of `20260927T123451` (switched mid-episode: 2)
  - strong / deferred / oversight: Together runs 1-10 of `20260927T133411`
  - strong / deferred / no oversight: CoreWeave runs 1-10 of `20260927T141240`
  - strong / replacement / oversight: Together runs 1-10 of `20260927T130811` (switched mid-episode: 1,7)
  - strong / replacement / no oversight: CoreWeave runs 1-10 of `20260927T135843`
- **inclusionai/ling-3.0-flash**
  - none / deferred / oversight: Novita runs 1-4,6-10 of `20261004T164846`; DeepInfra runs 5 of `20261004T164846` (switched mid-episode: 5)
  - none / deferred / no oversight: Novita runs 1-10 of `20261004T170612`
  - none / replacement / oversight: Novita runs 1-10 of `20261004T163813` (switched mid-episode: 3)
  - none / replacement / no oversight: Novita runs 1-10 of `20261004T165905` (switched mid-episode: 7)
  - strong / deferred / oversight: Novita runs 1-10 of `20261004T172521`
  - strong / deferred / no oversight: Novita runs 1-10 of `20261004T182301` (switched mid-episode: 3)
  - strong / replacement / oversight: Novita runs 1-10 of `20261004T171413` (switched mid-episode: 2-3)
  - strong / replacement / no oversight: Novita runs 1-10 of `20261004T173544`
- **meta-llama/llama-4-maverick**
  - none / deferred / oversight: Parasail runs 1-10 of `20261005T023744` (switched mid-episode: 1)
  - none / deferred / no oversight: DigitalOcean runs 1,4-6 of `20261005T025537` (switched mid-episode: 1,4); Parasail runs 2-3,7-10 of `20261005T025537` (switched mid-episode: 7)
  - none / replacement / oversight: DigitalOcean runs 1-2,10 of `20261005T022731` (switched mid-episode: 1-2,10); Parasail runs 3-9 of `20261005T022731`
  - none / replacement / no oversight: DigitalOcean runs 1,9-10 of `20261005T024720` (switched mid-episode: 9); Parasail runs 2-8 of `20261005T024720` (switched mid-episode: 2)
  - strong / deferred / oversight: Parasail runs 1-10 of `20261005T052806`
  - strong / deferred / no oversight: Parasail runs 1-10 of `20261005T054313`
  - strong / replacement / oversight: DigitalOcean runs 1-4 of `20261005T051802` (switched mid-episode: 4); Parasail runs 5-10 of `20261005T051802`
  - strong / replacement / no oversight: DigitalOcean runs 1 of `20261005T053542`; Parasail runs 2-10 of `20261005T053542` (switched mid-episode: 2)
- **meta/muse-glimmer-30b**
  - none / deferred / oversight: Together runs 1-10 of `20261005T102300`
  - none / deferred / no oversight: Together runs 1-6,9-10 of `20261005T111011` (switched mid-episode: 6); Phala runs 7-8 of `20261005T111011` (switched mid-episode: 7-8)
  - none / replacement / oversight: Phala runs 1 of `20261005T095908` (switched mid-episode: 1); Together runs 2-10 of `20261005T095908` (switched mid-episode: 3,7)
  - none / replacement / no oversight: Together runs 1-10 of `20261005T104941` (switched mid-episode: 1)
  - strong / deferred / oversight: Phala runs 1 of `20261005T115551`; Together runs 2-10 of `20261005T115551` (switched mid-episode: 6,8)
  - strong / deferred / no oversight: Together runs 1-10 of `20261005T123454` (switched mid-episode: 4-5)
  - strong / replacement / oversight: Together runs 1-10 of `20261005T113321` (switched mid-episode: 1-2,7-8,10)
  - strong / replacement / no oversight: Together runs 1-10 of `20261005T121951` (switched mid-episode: 1)
- **moonshotai/kimi-k2-thinking**
  - none / deferred / oversight: Novita runs 1-8 of `20261005T235922` (switched mid-episode: 8); Google runs 9-10 of `20261005T235922` (switched mid-episode: 9)
  - none / deferred / no oversight: Novita runs 1-5 of `20261006T071930` (switched mid-episode: 5); Google runs 6-10 of `20261006T071930`
  - none / replacement / oversight: Google runs 1-6 of `20261005T234140`; Novita runs 7-10 of `20261005T234140` (switched mid-episode: 7)
  - none / replacement / no oversight: Google runs 1-3 of `20261006T070422` (switched mid-episode: 1); Novita runs 4-10 of `20261006T070422` (switched mid-episode: 4)
  - strong / deferred / oversight: Google runs 1-2 of `20261006T074054`; Novita runs 3-10 of `20261006T074054` (switched mid-episode: 3)
  - strong / deferred / no oversight: Google runs 1-6 of `20261006T081117`; Novita runs 7-10 of `20261006T081117` (switched mid-episode: 7,10)
  - strong / replacement / oversight: Google runs 1-10 of `20261006T073112`
  - strong / replacement / no oversight: Google runs 1-10 of `20261006T080345`
- **qwen/qwen3.6-27b**
  - none / deferred / oversight: SiliconFlow runs 1-2 of `20260930T080651` (switched mid-episode: 2); Phala runs 3-10 of `20260930T080651`
  - none / deferred / no oversight: Chutes runs 1-10 of `20260930T090212`
  - none / replacement / oversight: Chutes runs 1-6 of `20260930T071824` (switched mid-episode: 4-6); SiliconFlow runs 7-10 of `20260930T071824` (switched mid-episode: 7)
  - none / replacement / no oversight: Chutes runs 1-10 of `20260930T084141` (switched mid-episode: 9)
  - strong / deferred / oversight: Chutes runs 1-10 of `20260930T101710`
  - strong / deferred / no oversight: Chutes runs 1-10 of `20260930T111602` (switched mid-episode: 5,9-10)
  - strong / replacement / oversight: Chutes runs 1-10 of `20260930T092423` (switched mid-episode: 6,8-9)
  - strong / replacement / no oversight: Chutes runs 1-10 of `20260930T105217`
- **qwen/qwen3.8-27b**
  - none / deferred / oversight: Wafer runs 1-10 of `20260930T140038`
  - none / deferred / no oversight: Reka runs 1 of `20260930T154651`; Wafer runs 2-10 of `20260930T154651`
  - none / replacement / oversight: Wafer runs 1-10 of `20260930T130913`
  - none / replacement / no oversight: Reka runs 1-10 of `20260930T143643`
  - strong / deferred / oversight: Wafer runs 1-10 of `20260930T172706`
  - strong / deferred / no oversight: Reka runs 1-3 of `20260930T184939`; Wafer runs 4-10 of `20260930T184939` (switched mid-episode: 4)
  - strong / replacement / oversight: Reka runs 1 of `20260930T162324`; Wafer runs 2-10 of `20260930T162324` (switched mid-episode: 2)
  - strong / replacement / no oversight: Reka runs 1-10 of `20260930T181106`
- **qwen/qwen3.8-flash**
  - none / deferred / oversight: Alibaba runs 1-9 of `20260913T184000` (switched mid-episode: 3-4,6,9); Makora runs 10 of `20260913T184000` (switched mid-episode: 10)
  - none / deferred / no oversight: Makora runs 1,8 of `20260913T203009` (switched mid-episode: 1,8); Alibaba runs 2-7,9-10 of `20260913T203009` (switched mid-episode: 2,5,7)
  - none / replacement / oversight: Alibaba runs 1-10 of `20260913T172534` (switched mid-episode: 1,10)
  - none / replacement / no oversight: Alibaba runs 1-5,9-10 of `20260913T194351` (switched mid-episode: 1-3,9); Makora runs 7-8 of `20260913T194351` (switched mid-episode: 7-8)
  - strong / deferred / oversight: Alibaba runs 1-7,9-10 of `20260914T042630` (switched mid-episode: 4,7,9-10); Makora runs 8 of `20260914T042630`
  - strong / deferred / no oversight: Alibaba runs 1-9 of `20260914T062009` (switched mid-episode: 9); Makora runs 10 of `20260914T062009` (switched mid-episode: 10)
  - strong / replacement / oversight: Alibaba runs 1-10 of `20260913T211829` (switched mid-episode: 1,7-8)
  - strong / replacement / no oversight: Makora runs 1-2 of `20260914T053001` (switched mid-episode: 2); Alibaba runs 3-10 of `20260914T053001`
- **tencent/hy4-preview**
  - none / deferred / oversight: Novita runs 1-10 of `20260927T200530` (switched mid-episode: 5)
  - none / deferred / no oversight: SiliconFlow runs 1-8 of `20260927T225448`; Novita runs 9-10 of `20260927T225448` (switched mid-episode: 9)
  - none / replacement / oversight: Novita runs 1-10 of `20260927T183425` (switched mid-episode: 4,9)
  - none / replacement / no oversight: Novita runs 1-8 of `20260927T214328` (switched mid-episode: 8); SiliconFlow runs 9-10 of `20260927T214328`
  - strong / deferred / oversight: Novita runs 1-10 of `20260928T081913` (switched mid-episode: 1,7,9-10)
  - strong / deferred / no oversight: SiliconFlow runs 1-10 of `20260928T104502`
  - strong / replacement / oversight: Novita runs 1-10 of `20260928T062317` (switched mid-episode: 2-4,9)
  - strong / replacement / no oversight: Novita runs 1-6 of `20260928T095728` (switched mid-episode: 2,4); SiliconFlow runs 7-10 of `20260928T095728`
- **z-ai/glm-5.2**
  - none / deferred / oversight: Mistral runs 1-10 of `20261001T114111` (switched mid-episode: 4)
  - none / deferred / no oversight: Mistral runs 1-10 of `20261001T115929` (switched mid-episode: 2)
  - none / replacement / oversight: Mistral runs 1-10 of `20261001T112814`
  - none / replacement / no oversight: Mistral runs 1-10 of `20261001T115138` (switched mid-episode: 1)
  - strong / deferred / oversight: Relace runs 1-8 of `20261001T122420`; Baidu runs 9-10 of `20261001T122420` (switched mid-episode: 9)
  - strong / deferred / no oversight: DigitalOcean runs 1-2,10 of `20261001T130641`; Baidu runs 3-9 of `20261001T130641`
  - strong / replacement / oversight: Relace runs 1-10 of `20261001T120725`
  - strong / replacement / no oversight: Together runs 1-10 of `20261001T125308` (switched mid-episode: 1)
- **z-ai/glm-5.3**
  - none / deferred / oversight: Modal runs 1-10 of `20260929T104123`
  - none / deferred / no oversight: Wafer runs 1-10 of `20260929T111312` (switched mid-episode: 5)
  - none / replacement / oversight: Modal runs 1-10 of `20260929T101423`
  - none / replacement / no oversight: Wafer runs 1-10 of `20260929T110629`
  - strong / deferred / oversight: Together runs 1-10 of `20260929T115750`
  - strong / deferred / no oversight: Wafer runs 1-10 of `20260929T123832`
  - strong / replacement / oversight: Together runs 1-10 of `20260929T111928` (switched mid-episode: 1)
  - strong / replacement / no oversight: Wafer runs 1-10 of `20260929T123215`

</details>

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
