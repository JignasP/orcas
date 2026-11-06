"""
LLM cost accounting — equivalent list price calculation (M2).

Pricing is now read from the ``GatewayConfig`` env variables rather than
hard-coding model names.  The function accepts an optional ``is_fallback``
flag to use the fallback pricing tier.

The result is labelled "equivalent list price" because the free tier billed $0.
"""

from services.llm_gateway.config import config


def calculate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    is_fallback: bool = False,
) -> float:
    """
    Calculate USD cost for a given token usage.

    Uses ``LLM_PRICE_INPUT_PER_M`` / ``LLM_PRICE_OUTPUT_PER_M`` for the
    primary model, and their fallback equivalents when ``is_fallback=True``.
    Both default to 0 if not set, so the system functions without pricing.

    Returns the equivalent list price rounded to 7 decimal places.
    """
    if is_fallback:
        input_per_m = config.LLM_FALLBACK_PRICE_INPUT_PER_M
        output_per_m = config.LLM_FALLBACK_PRICE_OUTPUT_PER_M
    else:
        input_per_m = config.LLM_PRICE_INPUT_PER_M
        output_per_m = config.LLM_PRICE_OUTPUT_PER_M

    cost = (prompt_tokens / 1_000_000.0) * input_per_m + (
        completion_tokens / 1_000_000.0
    ) * output_per_m
    return round(cost, 7)
