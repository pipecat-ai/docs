from pathlib import Path
from typing import Annotated

import typer

DEFAULT_TIMEOUT = 60

eval_app = typer.Typer(name="eval")


@eval_app.command("run")
def run(
    scenarios: list[Path] = typer.Argument(..., help="Scenario files."),
    bot_url: str = typer.Option("ws://localhost:7860/ws", "--bot-url", help="Agent URL."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print each turn."),
    timeout: int = typer.Option(DEFAULT_TIMEOUT, "--timeout", "-t", help="Seconds."),
    record_dir: str = typer.Option("recordings", "--record-dir", help="Recordings."),
    legacy_mode: bool = typer.Option(False, "--legacy-mode", help="Deprecated: use --mode."),
    old_flag: bool = typer.Option(False, "--old-flag", deprecated=True),
    older_flag: bool = typer.Option(False, "--older-flag", deprecated=True),
    secret: bool = typer.Option(False, "--secret", hidden=True),
    retries: Annotated[int, typer.Option("--retries", help="Retries per turn.")] = 3,
):
    pass


@eval_app.command("suite")
def suite(
    pattern: str = typer.Option(None, "--pattern", "-p", help="Scenario glob."),
    concurrency: int = typer.Option(4, "--concurrency", help="Agents at a time."),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop at the first failure."),
):
    pass


@eval_app.command("report")
def report(runs_dir: str = typer.Option("runs", "--runs-dir")):
    pass


@eval_app.command("debug-dump", hidden=True)
def debug_dump():
    pass
