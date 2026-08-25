# OpenRouter API & Routing Reference

## Base URL

```
https://openrouter.ai/api/v1
```

## Authentication

All requests must include:
```
Authorization: Bearer <OPENROUTER_API_KEY>
```

## Endpoints Used

### 1. List Models

```
GET /models
```

Returns all available models with pricing, context limits, and supported parameters.

### 2. Model Ranking

```
GET /models/ranking
```

Returns models sorted by weekly spend/popularity. Use this for the `popular` sort mode.
Response shape: `{"models": [{"id": "...", "position": 1, ...}]}`.

### 3. Chat Completions

```
POST /chat/completions
```

Body:
```json
{
  "model": "openai/gpt-4o",
  "messages": [{"role": "user", "content": "..."}],
  "max_tokens": 1024
}
```

Supports the standard OpenAI chat completion schema.

## Routing Strategy

| Mode     | Sort Key                              |
|----------|---------------------------------------|
| popular  | weekly_rank (ascending)               |
| budget   | price_per_token (ascending)           |
| balanced | 0.5 × rank + 0.5 × price (ascending) |

## Fallback

When calling with multiple models (ordered list), pass the full list to OpenRouter's
chat completions `model` field as a space-separated string:

```
model: "openai/gpt-4o anthropic/claude-3-haiku"
```

OpenRouter automatically falls back to the next model if the primary fails.

## Error Codes

| Code | Meaning                                    |
|------|--------------------------------------------|
| 401  | Invalid / expired / disabled API key       |
| 402  | Insufficient credits                       |
| 429  | Rate limited — honor `Retry-After` header  |
| 502  | Upstream provider unavailable              |
| 503  | Service temporarily down                   |

## Pricing Units

All prices in the API are in **USD**, per **token**. Multiply by 1,000,000 for per-million-token pricing.

Cache read discounts are already reflected in `input_cache_read` where applicable.
