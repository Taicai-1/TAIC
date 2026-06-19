"""Per-model LLM pricing (USD) and cost estimation.

Prices below are USD per 1,000,000 tokens (provider list prices). Keep this list
updated as providers change pricing; an unknown model falls back to a
deliberately non-zero estimate so the spend cap never treats it as free.
"""

# model -> (input_usd_per_million, output_usd_per_million)
_PER_M = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Mistral
    "mistral-large-latest": (2.00, 6.00),
    "mistral-small-latest": (0.20, 0.60),
    "open-mistral-nemo": (0.15, 0.15),
    # Gemini
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
}

# Fallback for unknown models: a mid/high estimate so caps stay conservative.
_FALLBACK_PER_M = (5.00, 15.00)


def get_model_pricing(model: str) -> tuple[float, float]:
    """Return (input_per_token, output_per_token) in USD for a model id.

    Strips an optional provider prefix (e.g. "openai:gpt-4o-mini" -> "gpt-4o-mini").
    """
    clean = (model or "").split(":")[-1].strip()
    inp_m, out_m = _PER_M.get(clean, _FALLBACK_PER_M)
    return (inp_m / 1_000_000, out_m / 1_000_000)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost for a single LLM call."""
    inp, out = get_model_pricing(model)
    return round((prompt_tokens or 0) * inp + (completion_tokens or 0) * out, 6)
