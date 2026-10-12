"""MEASURE-01: each model reports its input budget the way its own prediction enforces it."""

import pytest
from test_w08_models import examples

from career_lab.models.v3.core import UNLIMITED, InputSize
from career_lab.models.v3.encoder import AttentionEncoder
from career_lab.models.v3.ensemble import FusionCandidate
from career_lab.models.v3.linear import LinearCandidate


@pytest.mark.parametrize("variant", ["pack", "pair"])
def test_measure_01_attention_budget_matches_its_truncation_rule(variant: str) -> None:
    model = AttentionEncoder(variant=variant, dimension=4)
    model.fit(examples(), epochs=1)
    item = examples("dev", 1)[0].item
    size = model.measure(item)
    assert size.limit == model.max_tokens and size.tokens is not None and not size.exceeds
    model.max_tokens = size.tokens
    assert not model.measure(item).exceeds
    assert model.predict(item).reason_code != "encoder_input_truncated"
    model.max_tokens = size.tokens - 1
    assert model.measure(item).exceeds
    assert model.predict(item).reason_code == "encoder_input_truncated"


def test_measure_01_linear_has_no_budget_and_fusion_takes_the_stricter_side() -> None:
    linear = LinearCandidate()
    linear.fit(examples())
    attention = AttentionEncoder(dimension=4)
    attention.fit(examples(), epochs=1)
    item = examples("dev", 1)[0].item
    assert linear.measure(item) == UNLIMITED and not UNLIMITED.exceeds
    encoded = attention.measure(item)
    assert FusionCandidate(linear, attention, 0.5).measure(item) == encoded
    assert FusionCandidate(attention, linear, 0.5).measure(item) == encoded
    assert FusionCandidate(linear, attention, 0).measure(item) == UNLIMITED
    assert FusionCandidate(linear, attention, 1).measure(item) == encoded
    tight = AttentionEncoder(dimension=4)
    tight.fit(examples(), epochs=1)
    tight.max_tokens = encoded.tokens - 1
    assert FusionCandidate(attention, tight, 0.5).measure(item) == InputSize(
        encoded.tokens, encoded.tokens - 1
    )
