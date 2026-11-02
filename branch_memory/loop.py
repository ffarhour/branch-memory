"""The per-story loop and the resumable run over prompts and conditions."""

import asyncio
import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from .buffer import Buffer, BufferedMove
from .client import LLM, CallRecord, MalformedOutput, ModelOutputError, render_prompt, total_tokens
from .config import Config, temperature_from_tau, temperature_to_send


class PromptSpec(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    premise: str
    genre: str
    scenes: int = Field(ge=1)


class SceneRecord(BaseModel):
    index: int
    text: str
    word_count: int
    candidates: list[str] = []
    chosen_move: str | None = None
    rejected: list[str] = []
    choice_seed: int | None = None
    choice_index: int | None = None
    buffer: list[BufferedMove] = []


class StoryRecord(BaseModel):
    id: str
    condition: str
    tau: float
    premise: str
    genre: str
    target_scenes: int
    model: str
    temperature_computed: float
    temperature_sent: float | None
    status: str = "ok"
    failure: str | None = None
    scenes: list[SceneRecord] = []
    calls: list[CallRecord] = []
    total_tokens: int = 0


def load_prompts(path: Path) -> list[PromptSpec]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [PromptSpec.model_validate_json(line) for line in lines if line.strip()]


def parse_moves(raw: str, k: int) -> list[str]:
    """Parse {"moves": [...]} holding exactly k non-empty strings, or raise MalformedOutput."""
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw.strip(), re.DOTALL)
    try:
        data = json.loads(fenced.group(1) if fenced else raw)
    except json.JSONDecodeError as error:
        raise MalformedOutput(f"not valid JSON: {error}") from error
    moves = data.get("moves") if isinstance(data, dict) else None
    if not isinstance(moves, list) or len(moves) != k:
        raise MalformedOutput(f'expected an object with "moves" holding {k} items')
    if not all(isinstance(m, str) and m.strip() for m in moves):
        raise MalformedOutput("every move must be a non-empty string")
    return [m.strip() for m in moves]


def choice_seed(seed: int, prompt_id: str, scene: int) -> int:
    """Stable across processes and shared by conditions, unlike Python's built-in hash()."""
    digest = hashlib.sha256(f"{seed}:{prompt_id}:{scene}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def story_so_far(scenes: list[SceneRecord]) -> str:
    if not scenes:
        return "(Nothing yet. This is the opening scene.)"
    return "\n\n".join(f"Scene {s.index}\n{s.text}" for s in scenes)


async def _next_scene(
    llm: LLM, cfg: Config, spec: PromptSpec, story: StoryRecord, buffer: Buffer | None,
    index: int, total: int, temperature: float,
) -> SceneRecord:
    context = dict(
        premise=spec.premise, genre=spec.genre, scene=index, total=total,
        story=story_so_far(story.scenes),
    )
    scene = SceneRecord(index=index, text="", word_count=0)
    direction = ""
    if buffer is not None:
        scene.candidates = await llm.call_parsed(
            story.calls, "propose", index, render_prompt("propose_system"),
            render_prompt("propose_user", k=cfg.k, **context), temperature,
            lambda raw: parse_moves(raw, cfg.k),
        )
        scene.choice_seed = choice_seed(cfg.seed, spec.id, index)
        scene.choice_index = random.Random(scene.choice_seed).randrange(cfg.k)
        scene.chosen_move = scene.candidates[scene.choice_index]
        scene.rejected = [m for i, m in enumerate(scene.candidates) if i != scene.choice_index]
        buffer.update(index, scene.rejected)
        scene.buffer = buffer.snapshot()
        direction = render_prompt("write_direction", move=scene.chosen_move, buffer=buffer.render())
    user = render_prompt("write_user", direction=direction, **context)
    scene.text = await llm.call(
        story.calls, "write", index, render_prompt("write_system"), user, temperature
    )
    scene.word_count = len(scene.text.split())
    return scene


async def run_story(llm: LLM, cfg: Config, spec: PromptSpec, condition: str) -> StoryRecord:
    """Write one story. API errors propagate; unusable model output is recorded as a failure."""
    temperature = temperature_from_tau(cfg.tau, cfg.t_base, cfg.t_gain)
    total = cfg.scenes or spec.scenes
    story = StoryRecord(
        id=spec.id, condition=condition, tau=cfg.tau, premise=spec.premise, genre=spec.genre,
        target_scenes=total, model=cfg.model, temperature_computed=temperature,
        temperature_sent=temperature_to_send(cfg.model, temperature),
    )
    buffer = Buffer(condition, cfg.tau, cfg.k, cfg.weight_floor) if condition != "A" else None
    try:
        for index in range(1, total + 1):
            story.scenes.append(
                await _next_scene(llm, cfg, spec, story, buffer, index, total, temperature)
            )
    except ModelOutputError as error:
        story.status, story.failure = "failed", str(error)
        print(f"FAILED {spec.id}/{condition}: {error}", file=sys.stderr)
    story.total_tokens = total_tokens(story.calls)
    return story


def story_path(out: Path, prompt_id: str, condition: str) -> Path:
    return out / "stories" / f"{prompt_id}__{condition}.json"


def write_json_atomic(path: Path, text: str) -> None:
    """Replace in one step, so an interrupted run never leaves a partial file to skip later."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


async def run_all(
    cfg: Config, prompts: list[PromptSpec], conditions: list[str], out: Path, sdk=None,
) -> int:
    """Run every missing story and return how many hit an API error and wrote no file."""
    llm = LLM(cfg, sdk)
    api_errors = 0

    async def one(spec: PromptSpec, condition: str) -> None:
        nonlocal api_errors
        path = story_path(out, spec.id, condition)
        if path.exists():
            print(f"skip {spec.id}/{condition}: already done")
            return
        try:
            story = await run_story(llm, cfg, spec, condition)
        except anthropic.APIError as error:
            api_errors += 1
            print(f"API ERROR {spec.id}/{condition}: {error}", file=sys.stderr)
            return
        write_json_atomic(path, story.model_dump_json(indent=1))
        print(f"{story.status} {spec.id}/{condition}: {story.total_tokens} tokens")

    await asyncio.gather(*(one(s, c) for s in prompts for c in conditions))
    return api_errors
