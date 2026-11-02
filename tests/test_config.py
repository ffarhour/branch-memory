import math

import pytest

from branch_memory.config import temperature_from_tau, temperature_to_send


def test_formula_at_defaults():
    assert temperature_from_tau(3.0) == pytest.approx(0.6 + 0.4 * (1 - math.exp(-1 / 3)))


def test_limits_and_direction():
    assert temperature_from_tau(0.01) == pytest.approx(1.0)
    assert temperature_from_tau(1e9) == pytest.approx(0.6)
    assert temperature_from_tau(1.0) > temperature_from_tau(5.0)


def test_clamped_to_api_range():
    assert temperature_from_tau(0.1, t_base=0.9, t_gain=0.9) == 1.0
    assert temperature_from_tau(5.0, t_base=-1.0, t_gain=0.1) == 0.0


def test_rejects_non_positive_tau():
    with pytest.raises(ValueError):
        temperature_from_tau(0)


def test_only_listed_models_get_a_temperature():
    assert temperature_to_send("claude-sonnet-5-5", 0.7) is None
    assert temperature_to_send("claude-sonnet-4-6", 0.7) == 0.7
    assert temperature_to_send("claude-sonnet-4-6", 0.0) == 0.0
