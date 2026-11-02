# branch-memory

A harness that tests one idea: LLM fiction is predictable because the model discards the alternatives it almost took at each choice point. If rejected choices keep pushing on the story for a while, with a weight that decays over scenes, does the fiction get less predictable without losing coherence?

Three conditions use the same prompts and model:

| Condition | What it does |
|---|---|
| A, plain | Writes each scene from the story so far. No moves, no buffer. |
| B, decay | Proposes `k` moves and picks one at random. The rest enter a buffer with weight `exp(-age / tau)`, dropped below 0.05. |
| C, fixed | Same as B, but weights stay 1.0. The buffer is capped at `(k-1) * ceil(tau * ln 20)`, dropping the oldest moves first. |

## How to run

```powershell
uv sync
uv run pytest
uv run branch-memory run --prompts prompts.jsonl --conditions A,B,C --tau 3 --k 4 --scenes 8 --out runs/full
uv run branch-memory judge --run runs/full
uv run branch-memory site --run runs/full --out site
```

`run` and `judge` read `ANTHROPIC_API_KEY` from the environment, or else from a `.env` file in the current directory (`ANTHROPIC_API_KEY=...`). The file is ignored by git, no other variable in it is read, and the harness never writes the key to disk.

`run` is resumable. It skips any story whose file exists in `<out>/stories/`, and it refuses to resume with different settings.

- API errors that remain after the SDK's retries write no file, so running again retries that story.
- Unusable model output (malformed JSON after one retry, a refusal, a response cut off) writes a story with `status: "failed"`. It counts as done. Delete its file to try again.
- Failed stories get no judge scores and appear on the page with the reason.

Prompts are in `prompts/*.md` and can be edited without touching code. Other defaults, including `t_base` and `t_gain`, are in `branch_memory/config.py`.

## Output

- `stories/<id>__<condition>.json`: scenes, chosen and rejected moves, buffer state with weights, choice seeds, and every API call with its prompts, raw response, temperature, tokens and latency.
- `judge/<id>__<condition>.json`: predictions, ratings and calls.
- `scores.csv`: `id, condition, tau, predictability, coherence, mean_scene_words, total_tokens`. `total_tokens` covers story generation and leaves out the judge.

## What the numbers mean

- **Predictability** (1 to 5, lower is less predictable): for each scene from 3 onward, the judge predicts the scene from the earlier ones, then rates how close the prediction was. The score is the mean rating.
- **Coherence** (1 to 5, higher is better): one rating of the whole story for contradictions and dangling threads.

The hypothesis predicts B has lower predictability than A with similar coherence. Comparing B with C shows whether the decay itself matters.

## What the judge is and isn't

The judge is a **cheap proxy and a stand-in until StoryScope ([arXiv 2604.03136](https://arxiv.org/abs/2604.03136)) is wired in**. See the stub in `metrics/storyscope.py`.

It is the same model that wrote the stories, and it grades its own predictions. It is not validated, and it does not measure how a human reader experiences a story. With 10 prompts, treat small differences as noise.

## Temperature

`temperature_from_tau` in `config.py` is a design choice to tune: `T = T_BASE + T_GAIN * (1 - exp(-1/tau))`. At `tau = 3` it gives 0.713.

**The default model does not use it.** `claude-sonnet-5-5` returns a 400 for a non-default temperature, so the harness computes T, records it, and does not send it. The judge's temperature 0 is treated the same way. All conditions still run at the same temperature, so temperature is not a confound, but on this model `tau` changes only the buffer.

To apply T(tau), use a model listed in `MODELS_ACCEPTING_TEMPERATURE`, such as `--model claude-sonnet-4-6`. The SDK is pinned below 2.0 for this reason: SDK 2.x sends API version `2026-10-21`, which rejects `temperature` on every model. `temperature_sent` on each call shows what happened.

## Known limitations

- **B and C barely differ on short stories.** At `tau = 3` a move stays above 0.05 for 9 scenes and the cap is 27 moves. An 8-scene story never drops a move in B and never reaches the cap in C, so the two see the same moves and differ only in the displayed weights. To test decay, use a smaller `tau` (at `tau = 1` a move lasts 3 scenes) or more scenes.
- **A differs from B in two ways.** B adds both random move selection and the buffer, and there is no condition with moves but no buffer. If B beats A, the cause could be the random choice alone. C does not separate this either.
- **"Same seeds" covers only the move choice.** B and C pick the same index at each scene, but the API has no seed parameter, so the candidates themselves differ.
- **Context length matches only between B and C.** A's prompts are shorter.
- Moves are proposed without seeing the buffer, as specified. Only the writing step sees it.
- The default model thinks adaptively before answering. That thinking is billed as output tokens, and `total_tokens` includes it.
- A refusal is recorded as a failed story. Automatic fallback to another model is off on purpose, because it would break "same model".
- Rate limits are handled by the SDK's retries with exponential backoff (`max_retries` in config).
