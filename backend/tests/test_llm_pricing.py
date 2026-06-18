from llm_pricing import estimate_cost, get_model_pricing


def test_known_model_cost():
    # gpt-4o-mini: 0.15/1M input, 0.60/1M output
    cost = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert round(cost, 4) == round(0.15 + 0.60, 4)


def test_provider_prefix_stripped():
    assert get_model_pricing("openai:gpt-4o-mini") == get_model_pricing("gpt-4o-mini")


def test_unknown_model_uses_fallback_not_zero():
    # Unknown models must NOT be free (would defeat the cap); fallback > 0.
    assert estimate_cost("totally-unknown-model", 1000, 1000) > 0


def test_zero_tokens_zero_cost():
    assert estimate_cost("gpt-4o-mini", 0, 0) == 0.0
