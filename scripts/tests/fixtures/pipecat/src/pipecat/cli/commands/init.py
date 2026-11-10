import typer


def init_command(
    ctx: typer.Context,
    target: str | None = typer.Argument(None, help="Project directory."),
    name: str | None = typer.Option(None, "--name", "-n", help="Project name."),
    context_hub: bool = typer.Option(
        True,
        "--context-hub/--no-context-hub",
        help="Register the Context Hub MCP server.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be written."),
):
    pass
