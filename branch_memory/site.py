"""Build the single self-contained results page."""

from html import escape
from pathlib import Path

from .judge import JudgeRecord, load_judgements, load_stories
from .loop import SceneRecord, StoryRecord

CONDITIONS = {
    "A": ("Plain", "Scene by scene, with no memory of other options."),
    "B": ("Decay", "Rejected moves stay in play and fade over the scenes."),
    "C": ("Fixed", "Rejected moves stay in play and never fade."),
}

CSS = """
:root{--page:#eef2f6;--panel:#fff;--ink:#17233a;--soft:#55617a;--line:#cdd5e1;
--a:#5b6b85;--b:#2547b8;--c:#8a5a00}
@media (prefers-color-scheme:dark){:root{--page:#141a26;--panel:#1c2433;--ink:#e6ebf4;
--soft:#a3aec2;--line:#37425a;--a:#9fb0cc;--b:#8ea8ff;--c:#e0b050}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
font:17px/1.6 Charter,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
.ui,summary,table,nav,.note{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1360px;margin:auto;padding:40px 24px 72px}
h1{font-size:clamp(2.2rem,6vw,3.6rem);line-height:1.05;margin:0 0 16px;font-weight:500}
.intro{max-width:66ch;font-size:1.1rem;margin:0}
nav{margin:24px 0 0;display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.92rem}
a{color:var(--b)}
a:focus-visible,summary:focus-visible{outline:2px solid var(--b);outline-offset:2px}
.prompt{margin-top:56px;scroll-margin-top:16px}
.prompt h2{font-size:1.5rem;line-height:1.3;font-weight:500;margin:4px 0 20px;max-width:60ch}
.genre{font-size:.92rem;color:var(--soft);margin:0}
.columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:start}
.story{background:var(--panel);border-top:4px solid var(--tone);padding:18px 20px 22px;min-width:0}
.story h3{margin:0;color:var(--tone);font-size:1.5rem;font-weight:500}
.story .ui{margin:2px 0 18px;color:var(--soft);font-size:.86rem;line-height:1.4}
.A{--tone:var(--a)}.B{--tone:var(--b)}.C{--tone:var(--c)}
.scene{margin:0 0 24px}
.scene h4{margin:0 0 6px;font:600 .82rem/1.4 system-ui,sans-serif;color:var(--soft)}
.scene p{margin:0 0 .8em;overflow-wrap:anywhere}
details{font-size:.9rem;line-height:1.45;border-left:2px solid var(--line);padding-left:10px}
summary{cursor:pointer;color:var(--soft);font-size:.84rem;padding:6px 0}
details b{font-family:system-ui,sans-serif;font-size:.8rem}
details ul{list-style:none;margin:6px 0 10px;padding:0}
details li{margin:0 0 10px}
.meter{display:block;height:4px;background:var(--line);margin-bottom:3px}
.meter i{display:block;height:100%;background:var(--tone)}
.w{font:600 .78rem system-ui,sans-serif;color:var(--soft)}
.failed{border-left:3px solid #b3261e;padding:8px 12px;font-size:.92rem}
.scores{overflow-x:auto;margin-top:16px}
table{border-collapse:collapse;width:100%;background:var(--panel);font-size:.92rem}
th,td{text-align:left;padding:8px 14px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-weight:600;color:var(--soft)}
.note{margin-top:56px;max-width:72ch;font-size:.9rem;color:var(--soft)}
@media (max-width:900px){.columns{grid-template-columns:minmax(0,1fr)}
.wrap{padding:28px 16px 56px}body{font-size:18px}}
"""


def _prose(text: str) -> str:
    return "".join(f"<p>{escape(p.strip())}</p>" for p in text.split("\n\n") if p.strip())


def _buffer_html(scene: SceneRecord) -> str:
    items = []
    for move in sorted(scene.buffer, key=lambda m: -m.weight):
        items.append(
            f'<li><span class="meter"><i style="width:{move.weight * 100:.0f}%"></i></span>'
            f'<span class="w">{move.weight:.2f}</span> {escape(move.text)}</li>'
        )
    return "".join(items)


def _scene_html(scene: SceneRecord) -> str:
    details = ""
    if scene.chosen_move:
        details = (
            f"<details><summary>Chosen move and buffer</summary>"
            f"<b>Chosen move</b><p>{escape(scene.chosen_move)}</p>"
            f"<b>Buffer ({len(scene.buffer)} moves)</b><ul>{_buffer_html(scene)}</ul></details>"
        )
    return (
        f'<section class="scene"><h4>Scene {scene.index}</h4>'
        f"{_prose(scene.text)}{details}</section>"
    )


def _story_html(condition: str, story: StoryRecord | None) -> str:
    name, about = CONDITIONS[condition]
    head = f'<h3>{condition}: {name}</h3><p class="ui">{about}</p>'
    if story is None:
        body = '<p class="failed ui">This condition has not been run for this premise.</p>'
    else:
        body = "".join(_scene_html(s) for s in story.scenes)
        if story.status != "ok":
            stopped = f"Stopped after {len(story.scenes)} of {story.target_scenes} scenes"
            body += f'<p class="failed ui">{stopped}: {escape(story.failure or "unknown")}</p>'
    return f'<article class="story {condition}">{head}{body}</article>'


def _number(value: float | None) -> str:
    return "not scored" if value is None else f"{value:.2f}".rstrip("0").rstrip(".")


def _scores_html(prompt_id: str, judged: dict[tuple[str, str], JudgeRecord]) -> str:
    rows = ""
    for condition, (name, _) in CONDITIONS.items():
        record = judged.get((prompt_id, condition))
        predictability = record.predictability if record else None
        coherence = record.coherence if record else None
        rows += (
            f"<tr><td>{condition}: {name}</td><td>{_number(predictability)}</td>"
            f"<td>{_number(coherence)}</td></tr>"
        )
    return (
        '<div class="scores"><table><thead><tr><th>Judge scores</th>'
        "<th>Predictability (1 to 5, lower is less predictable)</th>"
        f"<th>Coherence (1 to 5, higher is better)</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _temperature_note(stories: list[StoryRecord]) -> str:
    if not stories:
        return ""
    first = stories[0]
    if first.temperature_sent is None:
        return (
            f" The model, {escape(first.model)}, accepts only its default temperature, so the "
            f"value computed from tau ({first.temperature_computed:.2f}) was recorded but not sent."
        )
    return f" Every condition ran at temperature {first.temperature_sent:.2f}."


def build_page(run: Path) -> str:
    stories = load_stories(run)
    judged = load_judgements(run)
    by_key = {(s.id, s.condition): s for s in stories}
    ids = sorted({s.id for s in stories})
    nav, sections = "", ""
    for number, prompt_id in enumerate(ids, 1):
        first = next(s for s in stories if s.id == prompt_id)
        nav += f'<a href="#{prompt_id}">Story {number}: {escape(first.genre)}</a>'
        columns = "".join(_story_html(c, by_key.get((prompt_id, c))) for c in CONDITIONS)
        sections += (
            f'<section class="prompt" id="{prompt_id}"><p class="genre ui">{escape(first.genre)}</p>'
            f'<h2>{escape(first.premise)}</h2><div class="columns">{columns}</div>'
            f"{_scores_html(prompt_id, judged)}</section>"
        )
    tau = f"{stories[0].tau:g}" if stories else "unknown"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Branch memory</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Branch memory</h1>
<p class="intro">Each premise below was written three times by the same model. Story A is written
scene by scene with nothing else to go on. For B and C, the model proposes several next moves, one
is picked at random, and the rest are kept as unused directions that can colour later scenes.
In B those directions fade over the scenes; in C they never fade.</p>
<nav aria-label="Stories">{nav}</nav>
{sections}
<p class="note">The scores come from a stand-in judge, the same model asked to predict each scene
and then rate how close it came. They are a cheap proxy, not a validated measure. Memory length
tau was {tau} scenes.{_temperature_note(stories)}</p>
</div></body></html>
"""


def write_site(run: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(build_page(run), encoding="utf-8")
    return path
