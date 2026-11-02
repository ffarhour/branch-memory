"""Thin async wrapper over the Anthropic SDK: bounded concurrency, records, JSON retry."""

import asyncio
import re
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

import anthropic
from pydantic import BaseModel

from .config import Config, temperature_to_send

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
T = TypeVar("T")


class ModelOutputError(Exception):
    """The model answered, but the answer cannot be used (refusal, cut off, bad JSON)."""


class MalformedOutput(ValueError):
    """Raised by a parser when a response is not in the requested format."""


class CallRecord(BaseModel):
    step: str
    scene: int | None
    system: str
    user: str
    raw_response: str
    stop_reason: str | None
    temperature_computed: float
    temperature_sent: float | None
    input_tokens: int
    output_tokens: int
    latency_s: float
    request_id: str | None


def render_prompt(name: str, **values: str | int) -> str:
    """Fill {{placeholders}} in prompts/<name>.md. Inserted text is not scanned again."""
    template = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values[m.group(1)]), template)


def total_tokens(calls: list[CallRecord]) -> int:
    return sum(call.input_tokens + call.output_tokens for call in calls)


class LLM:
    def __init__(self, cfg: Config, sdk=None):
        self.cfg = cfg
        self.sdk = sdk or anthropic.AsyncAnthropic(max_retries=cfg.max_retries)
        self._slots = asyncio.Semaphore(cfg.concurrency)

    async def call(
        self, log: list[CallRecord], step: str, scene: int | None,
        system: str, user: str, temperature: float,
    ) -> str:
        """Make one request, append its record to log, and return the response text."""
        sent = temperature_to_send(self.cfg.model, temperature)
        extra = {"extra_body": {"temperature": sent}} if sent is not None else {}
        async with self._slots:
            start = time.perf_counter()
            response = await self.sdk.messages.create(
                model=self.cfg.model,
                max_tokens=self.cfg.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                **extra,
            )
            latency = time.perf_counter() - start
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        usage = response.usage
        log.append(CallRecord(
            step=step, scene=scene, system=system, user=user, raw_response=text,
            stop_reason=response.stop_reason, temperature_computed=temperature,
            temperature_sent=sent,
            input_tokens=usage.input_tokens
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0),
            output_tokens=usage.output_tokens, latency_s=round(latency, 3),
            request_id=getattr(response, "_request_id", None),
        ))
        if response.stop_reason != "end_turn":
            raise ModelOutputError(f"{step}: stop_reason={response.stop_reason}")
        if not text:
            raise ModelOutputError(f"{step}: empty response")
        return text

    async def call_parsed(
        self, log: list[CallRecord], step: str, scene: int | None, system: str, user: str,
        temperature: float, parse: Callable[[str], T],
    ) -> T:
        """Call and parse. On malformed output, retry once with a stricter instruction."""
        raw = await self.call(log, step, scene, system, user, temperature)
        try:
            return parse(raw)
        except MalformedOutput as error:
            print(f"MALFORMED {step} scene={scene}: {error}. Retrying once.", file=sys.stderr)
            stricter = f"{user}\n\n{render_prompt('json_retry', error=str(error))}"
        raw = await self.call(log, f"{step}_retry", scene, system, stricter, temperature)
        try:
            return parse(raw)
        except MalformedOutput as error:
            raise ModelOutputError(f"{step}: malformed after retry: {error}") from error
