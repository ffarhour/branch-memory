"""Run configuration and the temperature design choice."""

import math

from pydantic import BaseModel, Field

# Models that still accept a non-default temperature on API version 2023-06-01.
# Newer models return a 400 for it, so we leave the field out for them.
MODELS_ACCEPTING_TEMPERATURE = {"claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"}
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 1.0


class Config(BaseModel):
    model: str = "claude-sonnet-5-5"
    tau: float = Field(default=3.0, gt=0)
    k: int = Field(default=4, ge=2)
    scenes: int | None = Field(default=None, ge=1)  # None: use each prompt's own value
    seed: int = 0
    t_base: float = 0.6
    t_gain: float = 0.4
    weight_floor: float = 0.05
    concurrency: int = Field(default=4, ge=1)
    max_retries: int = 6  # the SDK backs off exponentially on 429, 5xx and connection errors
    max_tokens: int = 16000  # generous because adaptive thinking counts against this limit


def temperature_from_tau(tau: float, t_base: float = 0.6, t_gain: float = 0.4) -> float:
    """DESIGN CHOICE, tune me: map memory length to randomness with one parameter.

    1 - exp(-1/tau) is the fraction of a move's weight lost per scene. Short memory
    means fast decay, which here means more randomness: tau -> 0 gives T_BASE + T_GAIN,
    tau -> infinity gives T_BASE. The result is clamped to the API's allowed range.
    """
    if tau <= 0:
        raise ValueError(f"tau must be > 0, got {tau}")
    t = t_base + t_gain * (1 - math.exp(-1 / tau))
    return min(TEMPERATURE_MAX, max(TEMPERATURE_MIN, t))


def temperature_to_send(model: str, temperature: float) -> float | None:
    """Return the value to send, or None when this model only accepts its default."""
    return temperature if model in MODELS_ACCEPTING_TEMPERATURE else None
