import asyncio
import csv

from fakes import FakeSDK, message

from branch_memory.client import LLM
from branch_memory.config import Config
from branch_memory.judge import judge_run, judge_story, score_rows, summary_table, write_scores
from branch_memory.loop import PromptSpec, run_all, run_story
from branch_memory.site import build_page

SPEC = PromptSpec(id="p1", premise="A <door> & more.", genre="horror", scenes=4)


def make_run(path):
    assert asyncio.run(run_all(Config(), [SPEC], ["A", "B", "C"], path, FakeSDK())) == 0


def test_judge_scores_scene_three_onward_without_temperature(tmp_path):
    config = Config()
    story = asyncio.run(run_story(LLM(config, FakeSDK()), config, SPEC, "A"))
    sdk = FakeSDK()
    record = asyncio.run(judge_story(LLM(config, sdk), story))
    assert [s.scene for s in record.scenes] == [3, 4]
    assert record.predictability == 2 and record.coherence == 4
    assert len(sdk.requests) == 5
    assert all("extra_body" not in r for r in sdk.requests)
    # The judge predicting scene 3 must see scenes 1 and 2, and not scene 3.
    assert "Scene 2" in record.calls[0].user and "Scene 3" not in record.calls[0].user


def test_judge_sends_zero_temperature_when_model_accepts_it():
    config = Config(model="claude-sonnet-4-6")
    story = asyncio.run(run_story(LLM(config, FakeSDK()), config, SPEC, "A"))
    sdk = FakeSDK()
    asyncio.run(judge_story(LLM(config, sdk), story))
    assert all(r["extra_body"]["temperature"] == 0.0 for r in sdk.requests)


def test_scores_csv_summary_and_judge_resume(tmp_path):
    make_run(tmp_path)
    sdk = FakeSDK()
    asyncio.run(judge_run(Config(), tmp_path, sdk))
    calls = len(sdk.requests)
    asyncio.run(judge_run(Config(), tmp_path, sdk))
    assert len(sdk.requests) == calls

    rows = score_rows(tmp_path)
    path = write_scores(tmp_path, rows)
    with path.open(encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert list(written[0]) == [
        "id", "condition", "tau", "predictability", "coherence", "mean_scene_words", "total_tokens",
    ]
    assert len(written) == 3 and float(written[0]["predictability"]) == 2
    table = summary_table(rows)
    assert "cond" in table and "\nB " in table


def test_failed_story_is_not_judged_and_gets_a_blank_row(tmp_path):
    sdk = FakeSDK(script={1: message("", stop_reason="refusal")})
    asyncio.run(run_all(Config(), [SPEC], ["A"], tmp_path, sdk))
    judge_sdk = FakeSDK()
    asyncio.run(judge_run(Config(), tmp_path, judge_sdk))
    assert judge_sdk.requests == []
    assert score_rows(tmp_path)[0]["predictability"] is None
    assert "Stopped after 0 of 4 scenes" in build_page(tmp_path)


def test_page_is_self_contained_escaped_and_complete(tmp_path):
    make_run(tmp_path)
    asyncio.run(judge_run(Config(), tmp_path, FakeSDK()))
    page = build_page(tmp_path)
    assert "A &lt;door&gt; &amp; more." in page and "<door>" not in page
    assert "<script" not in page and "http" not in page and "<link" not in page
    for heading in ("A: Plain", "B: Decay", "C: Fixed", "Chosen move and buffer", "Judge scores"):
        assert heading in page
    assert "<details>" in page and "max-width:900px" in page
    assert "was recorded but not sent" in page
