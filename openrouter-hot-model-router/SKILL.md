---
name: openrouter-hot-model-router
description: Dynamically discover, compare, audit, recommend, and call currently
  popular OpenRouter AI models. Use when an agent needs a live top-model
  leaderboard, task-aware model selection by cost/context/modalities/tool
  support, SkillHub coverage checks, or resilient OpenRouter calls with ordered
  model fallbacks.
slug: openrouter-hot-model-router-b26bd65e
displayName: OpenRouter 热门模型路由与 Skill 覆盖审计
version: 1.0.1
summary: 动态获取热门模型排行，按任务与成本推荐模型，检查 SkillHub 覆盖情况，并支持安全调用与自动降级。
license: MIT
disable-model-invocation: true
---

# OpenRouter Hot Model Router

Use the bundled script as the deterministic source for live model data. Do not hardcode a leaderboard: popularity, availability, model IDs, and pricing change frequently.

## Quick start

Run commands from this skill directory:

```bash
python scripts/model_router.py list --limit 30
python scripts/model_router.py recommend --task "中文长文分析，需要工具调用" --limit 5
python scripts/model_router.py audit-skillhub --limit 30
```

Use `python3` instead of `python` when required by the environment. Add `--json` when machine-readable output is preferable.

## Select a model

1. Refresh the live catalog with `recommend`; never rely only on model names remembered from an earlier session.
2. Translate the user's actual constraints into flags:
   - Use `--mode popular` for adoption-first ranking.
   - Use `--mode budget` for batch or cost-sensitive work.
   - Use `--mode balanced` by default.
   - Add `--require-tools` for function or tool calling.
   - Add `--require-vision` for image inputs.
   - Add `--min-context N` for large repositories or long documents.
3. Present two or three candidates with model ID, weekly rank, context length, and estimated input/output price.
4. Explain that weekly popularity is an adoption signal, not a universal quality benchmark.
5. Keep preview, free, or newly listed models clearly labeled; do not imply stability guarantees.

## Audit SkillHub coverage

Run:

```bash
python scripts/model_router.py audit-skillhub --limit 30
```

Treat a model as covered only when a Skill's display name or slug contains the normalized model name. Do not count a Skill merely because its description mentions the model. Review exact matches before recommending duplication.

When coverage is missing, prefer one differentiated workflow over many near-identical wrappers. Useful differentiation includes Chinese prompt adaptation, structured outputs, cost controls, fallback routing, validation, and privacy-safe key handling. Never copy another author's Skill content or imply an unofficial Skill is vendor-authored.

## Call OpenRouter

Require the user to configure `OPENROUTER_API_KEY` in their own environment. Never ask them to paste the key into a prompt, command history, generated file, or published Skill.

```bash
python scripts/model_router.py call \
  --models openai/gpt-5.5 anthropic/claude-sonnet-5 \
  --prompt "Review this design and return three prioritized risks"
```

The model list is ordered. OpenRouter tries fallbacks when the primary model cannot complete the request. Report the actual model returned by the API rather than assuming the first candidate was used.

Before a paid call:

1. Show the selected model order and whether fallbacks are enabled.
2. Warn that the request can consume OpenRouter credits.
3. Avoid sending secrets, private files, or personal data unless the user explicitly authorizes that transmission.
4. Use `--max-tokens` to bound output cost.

## Interpret failures

- `401`: key is invalid, expired, or disabled.
- `402`: account or key lacks sufficient credits.
- `429`: rate limited; honor `Retry-After` before retrying.
- `502` or `503`: provider/model unavailable; use ordered fallbacks or try later.
- No candidates: relax only the least important filter and explain the change.

Read [references/api-and-routing.md](references/api-and-routing.md) when modifying endpoints, selection rules, or fallback behavior.
