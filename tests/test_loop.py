import asyncio
import json

import anthropic
import httpx2
import pytest
from fakes import FakeSDK, message, moves_json

from branch_memory.client import LLM, MalformedOutput
from branch_memory.config import Config
from branch_memory.judge import parse_rating
from branch_memory.loop import (
    PromptSpec, StoryRecord, choice_seed, parse_moves, run_all, run_story, story_path,
)

SPEC = PromptSpec(id="p1", premise="A door.", genre="horror", scenes=3)


def story(condition, sdk, **cfg):
    config = Config(**cfg)
    return asyncio.run(run_story(LLM(config, sdk), config, SPEC, condition))


def test_parse_moves_accepts_plain_and_fenced_json():
    assert parse_moves('{"moves": ["a", "b"]}', 2) == ["a", "b"]
    assert parse_moves('```json\n{"moves": ["a", "b"]}\n```', 2) == ["a", "b"]


@pytest.mark.parametrize("raw", [
    "not json", '["a", "b"]', '{"moves": ["a"]}', '{"moves": ["a", ""]}',
    '{"moves": ["a", 3]}', '{"other": ["a", "b"]}', 'Here you go: {"moves": ["a", "b"]}',
])
def test_parse_moves_rejects_bad_shapes(raw):
    with pytest.raises(MalformedOutput):
        parse_moves(raw, 2)


@pytest.mark.parametrize("raw", ["3", '{"closeness": 9}', '{"closeness": "3"}', '{"closeness": true}'])
def test_parse_rating_rejects_bad_values(raw):
    with pytest.raises(MalformedOutput):
        parse_rating(raw, "closeness")


def test_a_only_writes_and_shows_no_buffer():
    record = story("A", FakeSDK())
    assert [c.step for c in record.calls] == ["write"] * 3
    assert all(s.chosen_move is None for s in record.scenes)
    assert "Unused directions" not in record.calls[0].user
    assert record.total_tokens == 45


def test_b_records_choice_and_shows_buffer_as_pressure():
    record = story("B", FakeSDK())
    assert [c.step for c in record.calls] == ["propose", "write"] * 3
    first = record.scenes[0]
    assert first.chosen_move == first.candidates[first.choice_index]
    assert first.chosen_move not in first.rejected and len(first.rejected) == 3
    assert [len(s.buffer) for s in record.scenes] == [3, 6, 9]
    assert "Unused directions still in the air (weight):" in record.calls[1].user
    assert "NOT the plot" in record.calls[1].user


def test_b_and_c_pick_the_same_index_but_only_b_decays():
    b, c = story("B", FakeSDK()), story("C", FakeSDK())
    assert [s.choice_index for s in b.scenes] == [s.choice_index for s in c.scenes]
    assert b.scenes[2].buffer[0].weight < 1.0
    assert all(m.weight == 1.0 for s in c.scenes for m in s.buffer)


def test_choice_seed_is_stable():
    assert choice_seed(0, "p", 1) == choice_seed(0, "p", 1) != choice_seed(0, "p", 2)


def test_temperature_is_left_out_on_default_model():
    sdk = FakeSDK()
    record = story("A", sdk)
    assert all("extra_body" not in r and "temperature" not in r for r in sdk.requests)
    assert record.temperature_sent is None
    assert record.temperature_computed == pytest.approx(0.7134, abs=1e-3)


def test_temperature_is_sent_on_model_that_accepts_it():
    sdk = FakeSDK()
    record = story("A", sdk, model="claude-sonnet-4-6")
    assert sdk.requests[0]["extra_body"]["temperature"] == pytest.approx(0.7134, abs=1e-3)
    assert record.calls[0].temperature_sent == record.temperature_sent


def test_malformed_json_retries_once_with_stricter_instruction():
    sdk = FakeSDK(script={1: message("oops")})
    record = story("B", sdk)
    assert record.status == "ok"
    assert [c.step for c in record.calls[:2]] == ["propose", "propose_retry"]
    assert "could not be used" in record.calls[1].user


def test_malformed_json_twice_records_failure():
    sdk = FakeSDK(script={1: message("oops"), 2: message("still bad")})
    record = story("B", sdk)
    assert record.status == "failed" and "malformed after retry" in record.failure
    assert record.scenes == [] and len(record.calls) == 2


def test_refusal_records_failure_and_keeps_earlier_scenes():
    record = story("A", FakeSDK(script={2: message("", stop_reason="refusal")}))
    assert record.status == "failed" and "refusal" in record.failure
    assert len(record.scenes) == 1


def _rate_limit():
    request = httpx2.Request("POST", "https://example.test")
    return anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=request), body=None
    )


def test_run_skips_existing_files_and_api_error_leaves_no_file(tmp_path):
    config = Config(scenes=1)
    errors = asyncio.run(run_all(config, [SPEC], ["A"], tmp_path, FakeSDK(script={1: _rate_limit()})))
    assert errors == 1 and not story_path(tmp_path, "p1", "A").exists()

    sdk = FakeSDK()
    assert asyncio.run(run_all(config, [SPEC], ["A"], tmp_path, sdk)) == 0
    saved = StoryRecord.model_validate_json(story_path(tmp_path, "p1", "A").read_text("utf-8"))
    assert saved.status == "ok" and len(sdk.requests) == 1

    asyncio.run(run_all(config, [SPEC], ["A"], tmp_path, sdk))
    assert len(sdk.requests) == 1


def test_concurrency_is_bounded(tmp_path):
    active = peak = 0

    class Slow(FakeSDK):
        async def _create(self, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return await super()._create(**kwargs)

    specs = [SPEC.model_copy(update={"id": f"p{i}"}) for i in range(8)]
    sdk = Slow()
    sdk.messages.create = sdk._create
    asyncio.run(run_all(Config(scenes=1, concurrency=2), specs, ["A"], tmp_path, sdk))
    assert peak == 2


def test_moves_json_helper_is_valid():
    assert len(json.loads(moves_json(4))["moves"]) == 4
