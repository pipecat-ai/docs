"""The `pipecat` Typer app, built lazily as in pipecat."""


def _build_app():
    import typer

    from pipecat.cli.commands.eval import eval_app
    from pipecat.cli.commands.init import init_command

    app = typer.Typer(name="pipecat")

    app.command("init")(init_command)

    def _removed_create(ctx: typer.Context):
        raise typer.Exit(1)

    app.command("create", hidden=True)(_removed_create)

    app.add_typer(eval_app, name="eval")
    return app
