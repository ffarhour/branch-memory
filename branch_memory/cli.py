"""Command line: run, judge, site."""

import asyncio
import os
from datetime import datetime
from pathlib import Path

import click

from .config import Config, temperature_from_tau, temperature_to_send
from .judge import judge_run, score_rows, summary_table, write_scores
from .loop import load_prompts, run_all
from .site import write_site

CONFIG_FILE = "config.json"
KEY_NAME = "ANTHROPIC_API_KEY"


def _load_key_from_env_file(path: Path = Path(".env")) -> None:
    """Read only ANTHROPIC_API_KEY from .env. A value already in the environment wins."""
    if os.environ.get(KEY_NAME) or not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.strip().removeprefix("export ").partition("=")
        if separator and name.strip() == KEY_NAME:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[KEY_NAME] = value


def _require_key() -> None:
    _load_key_from_env_file()
    if not os.environ.get(KEY_NAME):
        raise click.ClickException(f"{KEY_NAME} is not set in the environment or in .env.")


def _prepare_run_dir(out: Path, cfg: Config) -> None:
    """Refuse to resume a run with different settings, which would mix results."""
    path = out / CONFIG_FILE
    if path.exists():
        saved = Config.model_validate_json(path.read_text(encoding="utf-8"))
        if saved != cfg.model_copy(update={"concurrency": saved.concurrency}):
            raise click.ClickException(f"{path} has different settings. Use a new --out.")
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.model_dump_json(indent=1), encoding="utf-8")


@click.group()
def main() -> None:
    """Test whether rejected plot choices with a decaying weight make fiction less predictable."""


@main.command()
@click.option("--prompts", type=click.Path(exists=True, path_type=Path), default="prompts.jsonl")
@click.option("--conditions", default="A,B,C", help="Comma-separated subset of A,B,C.")
@click.option("--tau", type=click.FloatRange(min=0, min_open=True), default=3.0)
@click.option("--k", type=click.IntRange(min=2), default=4)
@click.option("--scenes", type=click.IntRange(min=1), help="Override each prompt's scene count.")
@click.option("--out", type=click.Path(path_type=Path))
@click.option("--model", default=Config.model_fields["model"].default)
@click.option("--seed", type=int, default=0)
@click.option("--concurrency", type=click.IntRange(min=1), default=4)
def run(prompts, conditions, tau, k, scenes, out, model, seed, concurrency) -> None:
    """Generate stories. Stories whose output file exists are skipped."""
    chosen = [c.strip().upper() for c in conditions.split(",") if c.strip()]
    if not chosen or set(chosen) - {"A", "B", "C"}:
        raise click.BadParameter("use a subset of A,B,C", param_hint="--conditions")
    _require_key()
    cfg = Config(model=model, tau=tau, k=k, scenes=scenes, seed=seed, concurrency=concurrency)
    out = out or Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    _prepare_run_dir(out, cfg)
    temperature = temperature_from_tau(cfg.tau, cfg.t_base, cfg.t_gain)
    if temperature_to_send(cfg.model, temperature) is None:
        click.echo(
            f"WARNING: {cfg.model} accepts only its default temperature. "
            f"T(tau)={temperature:.3f} is recorded but not sent.", err=True,
        )
    errors = asyncio.run(run_all(cfg, load_prompts(prompts), chosen, out))
    click.echo(f"Run directory: {out}")
    if errors:
        raise click.ClickException(f"{errors} stories hit API errors. Run again to resume.")


@main.command()
@click.option("--run", "run_dir", type=click.Path(exists=True, path_type=Path), required=True)
def judge(run_dir: Path) -> None:
    """Score a run with the proxy judge, then write scores.csv and print a summary."""
    _require_key()
    cfg = Config.model_validate_json((run_dir / CONFIG_FILE).read_text(encoding="utf-8"))
    errors = asyncio.run(judge_run(cfg, run_dir))
    rows = score_rows(run_dir)
    click.echo(f"Wrote {write_scores(run_dir, rows)}")
    click.echo("PROXY judge, not StoryScope. Scores are 1 to 5.")
    click.echo(summary_table(rows))
    if errors:
        raise click.ClickException(f"{errors} stories hit API errors. Run judge again to resume.")


@main.command()
@click.option("--run", "run_dir", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), default="site")
def site(run_dir: Path, out: Path) -> None:
    """Write a single self-contained index.html."""
    click.echo(f"Wrote {write_site(run_dir, out)}")
