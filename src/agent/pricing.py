from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPricing:
    input_per_m: float
    output_per_m: float
    cache_write_per_m: float
    cache_read_per_m: float


# Цены актуальны на 2026 (USD за 1M токенов).
# Источник: https://docs.anthropic.com/en/docs/about-claude/models
SONNET_4 = ModelPricing(
    input_per_m=3.0, output_per_m=15.0, cache_write_per_m=3.75, cache_read_per_m=0.30
)
OPUS_4 = ModelPricing(
    input_per_m=15.0, output_per_m=75.0, cache_write_per_m=18.75, cache_read_per_m=1.50
)
HAIKU_4 = ModelPricing(
    input_per_m=1.0, output_per_m=5.0, cache_write_per_m=1.25, cache_read_per_m=0.10
)

# Конкретные ID моделей → их прайс. Поддерживаются короткие алиасы;
# при несовпадении применяется prefix-match по ключам ниже.
PRICING: dict[str, ModelPricing] = {
    "claude-haiku-4-5": HAIKU_4,
    "claude-sonnet-4-5": SONNET_4,
    "claude-sonnet-4-6": SONNET_4,
    "claude-opus-4-6": OPUS_4,
    "claude-opus-4-7": OPUS_4,
}

DEFAULT_PRICING = SONNET_4


def resolve_pricing(model: str) -> ModelPricing:
    if model in PRICING:
        return PRICING[model]
    for key, p in PRICING.items():
        if model.startswith(key):
            return p
    return DEFAULT_PRICING


def estimate_cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    p = resolve_pricing(model)
    total = (
        input_tokens * p.input_per_m
        + output_tokens * p.output_per_m
        + cache_creation_tokens * p.cache_write_per_m
        + cache_read_tokens * p.cache_read_per_m
    ) / 1_000_000
    return round(total, 6)
