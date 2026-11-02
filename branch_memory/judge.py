"""Cheap proxy judge. A stand-in until StoryScope is wired in; see metrics/storyscope.py."""

import asyncio
import csv
import json
import statistics
import sys
from pathlib import Path

import anthropic
from pydantic import BaseModel

from .client import LLM, CallRecord, MalformedOutput, ModelOutputError, render_prompt
from .config import Config
from .loop import SceneRecord, StoryRecord, story_so_far, write_json_atomic

JUDGE_TEMPERATURE = 0.0
FIRST_JUDGED_SCENE = 3
CSV_FIELDS = [
    "id", "condition", "tau", "predictability", "coherence", "mean_scene_words", "total_tokens",
]


class SceneJudgement(BaseModel):
    scene: int
    prediction: str
    closeness: int


class JudgeRecord(BaseModel):
    id: str
    condition: str
    status: str = "ok"
    failure: str | None = None
    scenes: list[SceneJudgement] = []
    predictability: float | None = None
    coherence: int | None = None
    coherence_reason: str | None = None
    calls: list[CallRecord] = []


def parse_rating(raw: str, key: str) -> tuple[int, dict]:
    """Parse a JSON object whose `key` holds an integer from 1 to 5."""
    try:
        data = json.loads(raw.strip().removeprefix("```json").removesuffix("```"))
    except json.JSONDecodeError as error:
        raise MalformedOutput(f"not valid JSON: {error}") from error
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise MalformedOutput(f'expected "{key}" to be an integer from 1 to 5')
    return value, data


async def _judge_scene(
    llm: LLM, story: StoryRecord, scene: SceneRecord, log: list[CallRecord]
) -> SceneJudgement:
    earlier = [s for s in story.scenes if s.index < scene.index]
    system = render_prompt("judge_system")
    prediction = await llm.call(
        log, "judge_predict", scene.index, system,
        render_prompt(
            "judge_predict", premise=story.premise, genre=story.genre,
            story=story_so_far(earlier), scene=scene.index,
        ),
        JUDGE_TEMPERATURE,
    )
    closeness, _ = await llm.call_parsed(
        log, "judge_rate", scene.index, system,
        render_prompt("judge_rate", prediction=prediction, actual=scene.text),
        JUDGE_TEMPERATURE, lambda raw: parse_rating(raw, "closeness"),
    )
    return SceneJudgement(scene=scene.index, prediction=prediction, closeness=closeness)


async def judge_story(llm: LLM, story: StoryRecord) -> JudgeRecord:
    record = JudgeRecord(id=story.id, condition=story.condition)
    try:
        for scene in story.scenes:
            if scene.index >= FIRST_JUDGED_SCENE:
                record.scenes.append(await _judge_scene(llm, story, scene, record.calls))
        record.coherence, data = await llm.call_parsed(
            record.calls, "judge_coherence", None, render_prompt("judge_system"),
            render_prompt(
                "judge_coherence", premise=story.premise, genre=story.genre,
                story=story_so_far(story.scenes),
            ),
            JUDGE_TEMPERATURE, lambda raw: parse_rating(raw, "coherence"),
        )
        record.coherence_reason = str(data.get("reason", ""))
    except ModelOutputError as error:
        record.status, record.failure = "failed", str(error)
        print(f"JUDGE FAILED {story.id}/{story.condition}: {error}", file=sys.stderr)
    if record.scenes:
        record.predictability = statistics.mean(s.closeness for s in record.scenes)
    return record


def load_stories(run: Path) -> list[StoryRecord]:
    paths = sorted((run / "stories").glob("*.json"))
    return [StoryRecord.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]


def load_judgements(run: Path) -> dict[tuple[str, str], JudgeRecord]:
    records = [
        JudgeRecord.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((run / "judge").glob("*.json"))
    ]
    return {(r.id, r.condition): r for r in records}


async def judge_run(cfg: Config, run: Path, sdk=None) -> int:
    """Judge finished stories not yet judged. Returns the number of API errors."""
    llm = LLM(cfg, sdk)
    api_errors = 0

    async def one(story: StoryRecord) -> None:
        nonlocal api_errors
        path = run / "judge" / f"{story.id}__{story.condition}.json"
        if story.status != "ok":
            print(f"not judged {story.id}/{story.condition}: story failed")
        elif not path.exists():
            try:
                record = await judge_story(llm, story)
            except anthropic.APIError as error:
                api_errors += 1
                print(f"API ERROR judging {story.id}/{story.condition}: {error}", file=sys.stderr)
                return
            write_json_atomic(path, record.model_dump_json(indent=1))

    await asyncio.gather(*(one(s) for s in load_stories(run)))
    return api_errors


def score_rows(run: Path) -> list[dict]:
    judgements = load_judgements(run)
    rows = []
    for story in load_stories(run):
        judged = judgements.get((story.id, story.condition))
        words = [s.word_count for s in story.scenes]
        rows.append({
            "id": story.id, "condition": story.condition, "tau": story.tau,
            "predictability": judged.predictability if judged else None,
            "coherence": judged.coherence if judged else None,
            "mean_scene_words": round(statistics.mean(words), 1) if words else None,
            "total_tokens": story.total_tokens,
        })
    return rows


def write_scores(run: Path, rows: list[dict]) -> Path:
    path = run / "scores.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _mean_std(values: list[float]) -> str:
    if not values:
        return "-"
    std = statistics.stdev(values) if len(values) > 1 else float("nan")
    return f"{statistics.mean(values):.2f} +/- {std:.2f}"


def summary_table(rows: list[dict]) -> str:
    """Mean and sample standard deviation per condition. Blank scores are left out."""
    lines = [f"{'cond':<5}{'n':>3}  {'predictability':<16}{'coherence':<16}{'words':<20}tokens"]
    for condition in sorted({row["condition"] for row in rows}):
        group = [row for row in rows if row["condition"] == condition]
        columns = [
            [row[field] for row in group if row[field] is not None]
            for field in ("predictability", "coherence", "mean_scene_words", "total_tokens")
        ]
        predictability, coherence, words, tokens = map(_mean_std, columns)
        lines.append(
            f"{condition:<5}{len(group):>3}  {predictability:<16}{coherence:<16}{words:<20}{tokens}"
        )
    return "\n".join(lines)
