# Full run: tau 3, 2026-11-02

**Result:** both conditions that keep rejected moves scored as less predictable than plain generation. Coherence may have dropped, and this run cannot say whether decay itself helps. All scores come from a proxy judge that is the same model that wrote the stories, so this is a first signal and not proof.

- [Read the stories and scene-level detail](index.html). GitHub shows this file as source, so download it and open it in a browser.
- [Per-story scores](scores.csv)

## Setup

| Setting | Value |
|---|---|
| Model | `claude-sonnet-5-5` |
| Stories | 10 prompts x 3 conditions = 30, all completed |
| Scenes per story | 8 |
| `tau` | 3 |
| `k` (moves proposed per scene) | 4 |
| Seed | 0 |

The conditions are A (plain), B (rejected moves with decaying weight) and C (rejected moves with fixed weight 1.0). See the [main README](../../README.md) for details.

## Scores

Predictability runs from 1 to 5, and lower means the judge's predictions were further from what happened. Coherence runs from 1 to 5, and higher is better. Values are means across the 10 prompts, with the standard deviation in brackets.

| Condition | Predictability | Coherence | Words per scene | Story tokens |
|---|---|---|---|---|
| A, plain | 2.70 (0.36) | 4.4 (0.52) | 229 | 21,481 |
| B, decay | 1.93 (0.45) | 3.9 (0.57) | 244 | 55,543 |
| C, fixed | 2.20 (0.28) | 4.1 (0.57) | 246 | 55,732 |

Each prompt ran under all three conditions, so these are differences within the same prompt. The range is a 95% t-interval. The p-value is from an exact two-sided sign-flip permutation test.

| Comparison | Mean difference | 95% range | p | Lower / same / higher |
|---|---|---|---|---|
| Predictability, B - A | -0.77 | -1.24 to -0.29 | 0.012 | 8 / 0 / 2 |
| Predictability, C - A | -0.50 | -0.80 to -0.20 | 0.010 | 9 / 0 / 1 |
| Predictability, B - C | -0.27 | -0.56 to 0.03 | 0.094 | 8 / 0 / 2 |
| Coherence, B - A | -0.50 | -1.01 to 0.01 | 0.125 | 6 / 3 / 1 |
| Coherence, C - A | -0.30 | -0.89 to 0.29 | 0.500 | 3 / 6 / 1 |
| Coherence, B - C | -0.20 | -0.65 to 0.25 | 0.625 | 3 / 6 / 1 |

These p-values are not corrected for running six tests. With a Bonferroni correction the threshold is 0.0083, and none of them clear it.

### Per prompt

| Prompt | Predictability A | B | C | Coherence A | B | C |
|---|---|---|---|---|---|---|
| bread-oath | 2.17 | 2.50 | 2.00 | 5 | 4 | 4 |
| dust-signal | 2.50 | 1.83 | 2.33 | 4 | 4 | 4 |
| ferry-wedding | 2.67 | 1.33 | 2.00 | 4 | 3 | 4 |
| orbit-garden | 3.00 | 1.67 | 2.00 | 4 | 5 | 5 |
| pigeon-case | 2.67 | 1.83 | 2.00 | 5 | 4 | 3 |
| salt-ledger | 2.50 | 2.00 | 2.67 | 4 | 4 | 4 |
| second-violin | 2.83 | 1.50 | 1.83 | 4 | 4 | 4 |
| tenth-floor | 2.50 | 2.00 | 2.17 | 5 | 4 | 5 |
| tide-clinic | 3.50 | 1.83 | 2.50 | 5 | 4 | 4 |
| winter-map | 2.67 | 2.83 | 2.50 | 4 | 3 | 4 |

## What this does and does not show

**Stories with moves and a buffer were harder to predict.** B and C both scored lower than A on most prompts.

**The buffer may not be the cause.** A differs from B and C in two ways: they pick a move at random, and they also see the rejected moves. This run has no condition with random moves and no buffer, so random selection alone could explain the drop.

**Coherence is unresolved.** The data fits anything from no loss to a loss of about one point for B. No A story scored below 4, while 3 of 20 B and C stories scored 3. So "without losing coherence" is not established. The judge gave these reasons for those three stories:

- `ferry-wedding` B: a radio report has Julian at the island's head table, which contradicts his being in the cabin all along.
- `winter-map` B: scene 6 puts the church wall above the flood line, but scene 8 has the villagers removing the bell as the water rises.
- `pigeon-case` C: Mr. Okafor says he found the hawk feathers himself, then says Chidi brought them.

**This run does not test decay.** At `tau = 3` no move was dropped. Every B and C story ended with the same 24 moves in its buffer, so the only designed difference was the displayed weight (for example, 0.10 versus 1.00 for a scene 1 move at scene 8). B and C also got different candidate moves, because the API has no seed. The B - C gap is within noise.

**Scenes got longer.** B and C ran about 16 words per scene longer than A. Scenes over 250 words made up 30% of B and 33% of C, against 4% of A.

## Judge retries

The judge often wrote its reasoning before the JSON, which the parser rejects, so 102 of 180 closeness ratings needed a retry. Retries were not evenly spread: 47 of 60 in A, 27 of 60 in B and 28 of 60 in C.

This could have biased the scores, so I checked it. The rejected first answers all included a rating. Using those ratings instead of the retried ones leaves the same picture:

| | A | B | C | B - A | C - A | B - C |
|---|---|---|---|---|---|---|
| As recorded | 2.70 | 1.93 | 2.20 | -0.77 | -0.50 | -0.27 |
| Using first answers | 2.87 | 2.02 | 2.30 | -0.85 | -0.57 | -0.28 |

Retried scenes do have much higher ratings than the rest in every condition (2.56 to 2.96, against 1.42 to 1.77). The judge seems to write more when a prediction is close, so higher closeness causes the retry, rather than the retry raising the score. The first answer and the retry gave the same rating 81 times out of 102.

## Other limits

- The judge shares the writer's model and grades its own predictions. It says nothing direct about human readers.
- There are only 10 prompts, and coherence is one whole-number rating per story.
- `claude-sonnet-5-5` accepts only its default temperature, so T(tau) was recorded but never sent.
- API sampling has no seed, so a rerun will produce different stories.

## Cost

| | Tokens | Rate per million | Cost |
|---|---|---|---|
| Input | 1,761,398 | $2 | $3.52 |
| Output | 387,135 | $10 | $3.87 |
| Total | 2,148,533 | | **$7.39** |

This covers story generation and judging, and it is computed from recorded token counts at list price. Judging is about 38% of the tokens.

## Next run

1. Add a condition with random moves and no buffer, to separate random selection from the buffer.
2. Rerun B and C with `--tau 1`, where a move lasts only 3 scenes, so decay actually removes moves.
3. Change the judge's rating step so reasoning before the JSON is accepted or moved to a separate field. That removes most of the retry cost.

## Reproduce

Stories will differ because sampling is not seeded.

```powershell
uv run branch-memory run --prompts prompts.jsonl --conditions A,B,C --tau 3 --k 4 --scenes 8 --out runs/full
uv run branch-memory judge --run runs/full
uv run branch-memory site --run runs/full --out site
```

Raw run files, including every prompt and API response, stay in `runs/full` on the machine that ran them and are not in git.
